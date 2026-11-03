import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import {
  ApiError, describirError, request,
  type ListaPaginada, type LoginResponse, type Registro,
  type Usuario,
} from "./api";

type Tab = "clientes" | "tecnicos" | "ordenes" | "visitas" | "partes";
type ListService = "ms1" | "ms2" | "ms3" | "ms4";

const paginas: Array<{
  id: Exclude<Tab, "partes">;
  label: string;
  service: ListService;
  path: string;
  array: string;
  idField: string;
}> = [
  { id: "clientes", label: "Clientes", service: "ms1", path: "/clientes", array: "clientes", idField: "cliente_id" },
  { id: "tecnicos", label: "Técnicos", service: "ms2", path: "/tecnicos", array: "tecnicos", idField: "tecnico_id" },
  { id: "ordenes", label: "Órdenes", service: "ms3", path: "/ordenes", array: "ordenes", idField: "orden_id" },
  { id: "visitas", label: "Agenda", service: "ms4", path: "/visitas", array: "visitas", idField: "visita_id" },
];

function asString(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  return "";
}

function Login({ onReady }: { onReady: (session: LoginResponse) => void }) {
  const [tenant, setTenant] = useState("CLIMALIMA");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const login = await request<LoginResponse>("ms0", "/auth/login", {
        method: "POST",
        data: { tenant_id: tenant, email, password },
      });
      const perfil = await request<Usuario>("ms0", "/usuarios/me", {
        token: login.token,
      });
      if (perfil.tenant_id !== tenant) throw new Error("El perfil no corresponde a la empresa elegida");
      setPassword("");
      onReady({ ...login, usuario: perfil });
    } catch (err) {
      setPassword("");
      setError(describirError(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="auth-page">
      <section className="auth-card">
        <div className="eyebrow">Trazora FSM · Grupo 5</div>
        <h1>Tu operación de campo, bajo control.</h1>
        <p>Accede con la cuenta y empresa que te asignó el administrador.</p>
        <form onSubmit={submit} className="form">
          <label>
            Empresa
            <select value={tenant} onChange={(e) => setTenant(e.target.value)}>
              <option value="CLIMALIMA">ClimaLima</option>
              <option value="FRIOSUR">FríoSur</option>
              <option value="TECNINORTE">TecniNorte</option>
            </select>
          </label>
          <label>
            Correo
            <input type="email" autoComplete="username" required value={email}
              onChange={(e) => setEmail(e.target.value)} placeholder="usuario@empresa.com" />
          </label>
          <label>
            Contraseña
            <input type="password" autoComplete="current-password" required value={password}
              onChange={(e) => setPassword(e.target.value)} />
          </label>
          {error && <p role="alert" className="alert">{error}</p>}
          <button type="submit" disabled={busy} className="primary">
            {busy ? "Verificando..." : "Iniciar sesión"}
          </button>
        </form>
        <p className="note">
          La sesión se conserva en memoria, no en el navegador permanentemente.
          Al actualizar la página tendrás que iniciar sesión otra vez.
        </p>
      </section>
    </main>
  );
}

interface ListProps {
  service: ListService;
  path: string;
  array: string;
  idField: string;
  token: string;
  refreshKey?: number;
  onExpired: () => void;
}

function Lista({ service, path, array, idField, token, refreshKey = 0, onExpired }: ListProps) {
  const [items, setItems] = useState<Registro[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function cargar(next: string | null = null) {
    setBusy(true);
    setError("");
    try {
      const qs = new URLSearchParams({ limit: "20" });
      if (next) qs.set("cursor", next);
      const data = await request<ListaPaginada>(service, path + "?" + qs, { token });
      const lista = Array.isArray(data[array]) ? (data[array] as Registro[]) : [];
      setItems((prev) => next ? [...prev, ...lista] : lista);
      setCursor(typeof data.next_cursor === "string" ? data.next_cursor : null);
    } catch (err) {
      setError(describirError(err));
      if (err instanceof ApiError && err.status === 401) onExpired();
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    void cargar();
    // La navegación y los cambios de datos invalidan la página actual.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [service, path, array, token, refreshKey]);

  return (
    <section className="card">
      <div className="section-title">
        <div>
          <h2>Registros</h2>
          <p className="muted">Listado de tu empresa. Se muestran páginas de 20, no totales globales.</p>
        </div>
        <button type="button" onClick={() => void cargar()} disabled={busy}>Actualizar</button>
      </div>
      {error && <p className="alert" role="alert">{error}</p>}
      {!busy && !items.length && !error && <p className="empty">Todavía no hay registros en esta página.</p>}
      <div className="record-list">
        {items.map((item, index) => {
          const id = asString(item[idField]) || String(index);
          const title = asString(item["nombre"]) || asString(item["descripcion"]) ||
            asString(item["tipo_servicio"]) || asString(item["estado"]) || "Registro";
          return (
            <article className="record" key={id}>
              <div>
                <strong>{title}</strong>
                <small>{id}</small>
              </div>
              <div className="record-meta">
                <span>{asString(item["estado"]) || asString(item["prioridad"]) || asString(item["activo"])}</span>
                <span>{asString(item["tenant_id"])}</span>
              </div>
            </article>
          );
        })}
      </div>
      {cursor && (
        <button type="button" onClick={() => void cargar(cursor)} disabled={busy}>
          Cargar más
        </button>
      )}
      {busy && <p className="muted">Consultando AWS...</p>}
    </section>
  );
}

function CrearCliente({ token, onCreated, onExpired }: {
  token: string; onCreated: () => void; onExpired: () => void;
}) {
  const [nombre, setNombre] = useState("");
  const [correo, setCorreo] = useState("");
  const [telefono, setTelefono] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      await request("ms1", "/clientes", {
        method: "POST", token, data: { nombre, correo, telefono },
      });
      setNombre(""); setCorreo(""); setTelefono("");
      setMessage("Cliente creado y guardado en DynamoDB.");
      onCreated();
    } catch (err) {
      setMessage(describirError(err));
      if (err instanceof ApiError && err.status === 401) onExpired();
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <h2>Registrar cliente</h2>
      <p className="muted">El tenant se obtiene automáticamente del token autenticado.</p>
      <form className="form compact" onSubmit={submit}>
        <label>Nombre<input required value={nombre} onChange={(e) => setNombre(e.target.value)} maxLength={160} /></label>
        <label>Correo<input type="email" value={correo} onChange={(e) => setCorreo(e.target.value)} maxLength={254} /></label>
        <label>Teléfono<input value={telefono} onChange={(e) => setTelefono(e.target.value)} maxLength={40} /></label>
        <button className="primary" disabled={busy}>{busy ? "Guardando..." : "Crear cliente"}</button>
      </form>
      {message && <p role="status" className="muted">{message}</p>}
    </section>
  );
}

function PartePorVisita({ token, onExpired }: { token: string; onExpired: () => void }) {
  const [visitaId, setVisitaId] = useState("");
  const [parte, setParte] = useState<Registro | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  async function operar(create: boolean) {
    if (!/^[0-9a-f-]{36}$/.test(visitaId.trim())) {
      setMessage("Introduce el UUID de una visita existente en Agenda.");
      return;
    }
    setBusy(true);
    setMessage("");
    try {
      const result = await request<{ parte: Registro }>(
        "ms5", "/visitas/" + encodeURIComponent(visitaId.trim()) + "/partes",
        { token, ...(create ? { method: "POST", data: {} } : {}) },
      );
      setParte(result.parte);
      setMessage(create ? "Borrador creado correctamente." : "Borrador recuperado.");
    } catch (err) {
      setParte(null);
      setMessage(describirError(err));
      if (err instanceof ApiError && err.status === 401) onExpired();
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card">
      <h2>Partes de trabajo</h2>
      <p className="muted">MS5 no ofrece listado general; busca el parte mediante un ID de visita de MS4.</p>
      <label>ID de visita
        <input value={visitaId} onChange={(e) => setVisitaId(e.target.value)} placeholder="UUID de visita" />
      </label>
      <div className="actions">
        <button disabled={busy} onClick={() => void operar(false)}>Consultar borrador</button>
        <button disabled={busy} onClick={() => void operar(true)}>Crear borrador</button>
      </div>
      {message && <p role="status" className="muted">{message}</p>}
      {parte && (
        <div className="data-preview">
          <h3>Borrador {asString(parte["parte_id"])}</h3>
          <p>Estado: {asString(parte["estado"])}</p>
          <p>Resultado: {asString(parte["resultado"])}</p>
          <p>Versión: {asString(parte["version"])}</p>
          <p className="note">
            La edición completa y el formulario de evidencias S3 los implementará el equipo.
            No existe todavía un endpoint para finalizar este parte.
          </p>
        </div>
      )}
    </section>
  );
}

export default function App() {
  const [session, setSession] = useState<LoginResponse | null>(null);
  const [page, setPage] = useState<Tab>("clientes");
  const [clientRefresh, setClientRefresh] = useState(0);

  async function logout() {
    if (!session) return;
    try {
      await request("ms0", "/auth/logout", { method: "POST", data: {}, token: session.token });
    } catch {
      // Al no haber sesión persistida local, salir siempre deja de enviar el token.
    } finally {
      setSession(null);
    }
  }

  if (!session) return <Login onReady={setSession} />;

  const current = paginas.find((p) => p.id === page);
  const onExpired = () => setSession(null);

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">TRAZORA <span>FSM</span></div>
        <div className="session-meta">
          <span className="pill">{session.usuario.tenant_id}</span>
          <span>{session.usuario.rol}</span>
          <button type="button" onClick={() => void logout()}>Cerrar sesión</button>
        </div>
      </header>
      <div className="content-layout">
        <aside className="sidebar" aria-label="Secciones">
          <p className="sidebar-label">Operaciones</p>
          {paginas.map((item) => (
            <button key={item.id} type="button"
              className={page === item.id ? "nav-item active" : "nav-item"}
              onClick={() => setPage(item.id)}>{item.label}</button>
          ))}
          <button type="button" className={page === "partes" ? "nav-item active" : "nav-item"}
            onClick={() => setPage("partes")}>Partes y evidencias</button>
          <div className="sidebar-foot">MS0–MS5 · Entorno académico DEV</div>
        </aside>
        <main className="workspace">
          <div className="page-intro">
            <p className="eyebrow">Trazora · {session.usuario.tenant_id}</p>
            <h1>{current?.label || "Partes y evidencias"}</h1>
            <p>Sesión de {session.usuario.email}. Las acciones muestran datos reales del tenant autenticado.</p>
          </div>
          {page === "clientes" && (
            <CrearCliente token={session.token}
              onCreated={() => setClientRefresh((prev) => prev + 1)}
              onExpired={onExpired} />
          )}
          {current && (
            <Lista key={current.id} service={current.service} path={current.path}
              array={current.array} idField={current.idField}
              token={session.token} onExpired={onExpired}
              refreshKey={current.id === "clientes" ? clientRefresh : 0} />
          )}
          {page === "partes" && <PartePorVisita token={session.token} onExpired={onExpired} />}
          {page !== "clientes" && page !== "partes" && (
            <section className="info-strip">
              <strong>Próximo paso del equipo:</strong> diseñar los formularios de {current?.label.toLowerCase()}
              con los contratos reales de <code>docs/trazora/02_CONTRATOS_API.md</code>.
              No implementar rutas de cierre/finalización hasta que estén desplegadas.
            </section>
          )}
        </main>
      </div>
    </div>
  );
}
