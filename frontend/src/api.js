export const BASES = {
  ms0: import.meta.env.VITE_API_MS0 || '',
  ms1: import.meta.env.VITE_API_MS1 || '',
  ms2: import.meta.env.VITE_API_MS2 || '',
  ms3: import.meta.env.VITE_API_MS3 || '',
  ms4: import.meta.env.VITE_API_MS4 || '',
  ms5: import.meta.env.VITE_API_MS5 || '',
};

export class ApiError extends Error {
  constructor(status, message) {
    super(message);
    this.status = status;
    this.name = 'ApiError';
  }
}

export function explainError(error) {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'La sesión venció o las credenciales no son válidas. Inicia sesión nuevamente.';
    if (error.status === 403) return 'Tu rol no tiene permisos para realizar esta acción.';
    if (error.status === 404) return 'No encontramos el registro en tu empresa.';
    if (error.status === 409) return error.message || 'El registro cambió o existe un conflicto de horario.';
    if (error.status === 502 || error.status === 503) return 'Uno de los servicios AWS no respondió. Vuelve a intentarlo.';
    return error.message;
  }
  return error instanceof Error ? error.message : 'Ocurrió un error inesperado.';
}

export async function api(service, path, { method = 'GET', token, data, signal } = {}) {
  const base = BASES[service]?.replace(/\/$/, '');
  if (!base) throw new ApiError(0, `Configura VITE_API_${service.toUpperCase()} en tu archivo .env`);
  const headers = { Accept: 'application/json' };
  if (data !== undefined) headers['Content-Type'] = 'application/json';
  if (token) headers.Authorization = `Bearer ${token}`;
  let response;
  try {
    response = await fetch(base + path, {
      method, headers, body: data === undefined ? undefined : JSON.stringify(data), signal,
      cache: 'no-store',
    });
  } catch (err) {
    if (err?.name === 'AbortError') throw err;
    throw new ApiError(0, 'No se pudo conectar con AWS. Comprueba las URLs y la configuración CORS.');
  }
  const bodyText = await response.text();
  let payload = null;
  if (bodyText) {
    try { payload = JSON.parse(bodyText); } catch { /* HTML/empty response from API */ }
  }
  if (!response.ok || payload === null) {
    const msg = typeof payload?.error === 'string' ? payload.error : `Error HTTP ${response.status} al consultar ${service}`;
    throw new ApiError(response.status, msg);
  }
  return payload;
}

export async function getPage(service, path, token, cursor = null) {
  const query = new URLSearchParams({ limit: '30' });
  if (cursor) query.set('cursor', cursor);
  return api(service, `${path}?${query.toString()}`, { token });
}

export async function uploadEvidence(token, parteId, file) {
  if (!['image/png', 'image/jpeg'].includes(file.type)) throw new Error('Solo imágenes PNG o JPG.');
  if (file.size === 0 || file.size > 5 * 1024 * 1024) throw new Error('La imagen debe pesar entre 1 byte y 5 MB.');
  const ticket = await api('ms5', `/partes/${encodeURIComponent(parteId)}/evidencias`, {
    method: 'POST', token, data: { content_type: file.type },
  });
  const form = new FormData();
  Object.entries(ticket.upload?.fields || {}).forEach(([key, value]) => form.append(key, String(value)));
  form.append('file', file);
  const response = await fetch(ticket.upload.url, { method: 'POST', body: form });
  if (!response.ok) throw new Error(`S3 rechazó la imagen (${response.status}). Revisa el tamaño y CORS.`);
  return api('ms5', `/partes/${encodeURIComponent(parteId)}/evidencias/${encodeURIComponent(ticket.evidencia.evidencia_id)}/confirmar`, {
    method: 'POST', token, data: {},
  });
}

export function timeLima(value, options = {}) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat('es-PE', { timeZone: 'America/Lima', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', ...options }).format(date);
}
export function dayLima(value) {
  if (!value) return '';
  return new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Lima', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(value));
}
export const fmtShortId = (v) => v ? `${String(v).slice(0, 8).toUpperCase()}` : '—';
