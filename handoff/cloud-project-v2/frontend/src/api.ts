export type Service = "ms0" | "ms1" | "ms2" | "ms3" | "ms4" | "ms5";

const bases: Record<Service, string> = {
  ms0: import.meta.env.VITE_API_MS0 ?? "",
  ms1: import.meta.env.VITE_API_MS1 ?? "",
  ms2: import.meta.env.VITE_API_MS2 ?? "",
  ms3: import.meta.env.VITE_API_MS3 ?? "",
  ms4: import.meta.env.VITE_API_MS4 ?? "",
  ms5: import.meta.env.VITE_API_MS5 ?? "",
};

export interface Usuario {
  usuario_id: string;
  tenant_id: string;
  email: string;
  rol: "ADMIN" | "COORDINADOR" | "TECNICO";
  estado?: string;
}

export interface LoginResponse {
  token: string;
  token_type: "Bearer";
  expires_at: string;
  usuario: Usuario;
}

export interface ListaPaginada {
  next_cursor: string | null;
  [key: string]: unknown;
}

export type Registro = Record<string, unknown>;

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function request<T>(
  service: Service,
  path: string,
  options: { method?: string; token?: string; data?: unknown } = {},
): Promise<T> {
  const base = bases[service]?.replace(/\/$/, "");
  if (!base) throw new ApiError(0, "Falta configurar VITE_API_" + service.toUpperCase());

  const headers: Record<string, string> = { Accept: "application/json" };
  if (options.data !== undefined) headers["Content-Type"] = "application/json";
  if (options.token) headers.Authorization = "Bearer " + options.token;

  let response: Response;
  try {
    response = await fetch(base + path, {
      method: options.method ?? "GET",
      headers,
      body: options.data === undefined ? undefined : JSON.stringify(options.data),
    });
  } catch {
    throw new ApiError(0, "No se pudo conectar. Comprueba la URL de AWS y CORS.");
  }

  const raw = await response.text();
  let data: unknown = null;
  if (raw) {
    try {
      data = JSON.parse(raw) as unknown;
    } catch {
      data = null;
    }
  }

  if (!response.ok) {
    const detail =
      data && typeof data === "object" && "error" in data &&
      typeof (data as { error?: unknown }).error === "string"
        ? (data as { error: string }).error
        : "HTTP " + response.status + " al llamar a " + service;
    throw new ApiError(response.status, detail);
  }
  if (data === null) {
    throw new ApiError(response.status, "La API no devolvió un JSON válido");
  }
  return data as T;
}

export function describirError(error: unknown): string {
  if (!(error instanceof ApiError)) return "Error inesperado. Revisa la consola del servidor.";
  if (error.status === 401) {
    return /credenciales inválidas/i.test(error.message)
      ? "Credenciales inválidas. Comprueba empresa, correo y contraseña."
      : "Sesión no válida o vencida. Vuelve a iniciar sesión.";
  }
  if (error.status === 403) return "Tu rol no tiene permiso para realizar esta operación.";
  if (error.status === 404) return "Recurso no encontrado o fuera de tu empresa.";
  if (error.status === 409) return "Hay un conflicto de estado u horario. Actualiza y vuelve a intentarlo.";
  return error.message;
}
