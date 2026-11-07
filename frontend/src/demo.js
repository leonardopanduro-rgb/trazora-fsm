// Datos 100% ficticios para PREVISUALIZACIÓN. Nunca se presentan como valores AWS.
const id = (n) => `00000000-0000-4000-8000-${String(n).padStart(12, '0')}`;
const dateOf = (dayOffset, hour, minute = 0) => {
  const d = new Date();
  d.setDate(d.getDate() + dayOffset);
  d.setHours(hour, minute, 0, 0);
  return d.toISOString();
};
export const TENANTS = [
  { id: 'CLIMALIMA', name: 'ClimaLima', city: 'Lima Metropolitana' },
  { id: 'FRIOSUR', name: 'FríoSur', city: 'Sur de Lima' },
  { id: 'TECNINORTE', name: 'TecniNorte', city: 'Lima Norte' },
];
export function demoWorkspace(tenant = 'CLIMALIMA') {
  const clients = [
    ['Comercial Prado', 'operaciones@comercialprado.test', '955 304 820'],
    ['Edificio Aurora', 'gestion@aurora.test', '945 827 100'],
    ['Casa Editorial Norte', 'contacto@editorialnorte.test', '942 117 290'],
    ['Grupo Larco', 'servicios@larco.test', '987 014 602'],
    ['Studio Hiedra', 'hola@hiedra.test', '960 198 233'],
    ['Residencial Encanto', 'admin@encanto.test', '977 510 220'],
  ].map(([nombre, correo, telefono], i) => ({ cliente_id: id(i + 1), nombre, correo, telefono, activo: true, tenant_id: tenant, creado_en: dateOf(-12 + i, 11) }));
  const technicians = [
    ['Mateo Cárdenas', ['REPARACION', 'MANTENIMIENTO']],
    ['Valeria Ramos', ['INSTALACION', 'MANTENIMIENTO']],
    ['Luis Huamán', ['REPARACION', 'INSTALACION']],
    ['Camila Salazar', ['MANTENIMIENTO']],
  ].map(([nombre, especialidades], i) => ({ tecnico_id: id(i + 21), nombre, especialidades, activo: true, tenant_id: tenant }));
  const orders = [
    ['Equipo rooftop con bajo rendimiento', 'ALTA', 'EN_ATENCION', 'REPARACION', 0],
    ['Mantenimiento preventivo oficinas', 'MEDIA', 'ABIERTA', 'MANTENIMIENTO', 1],
    ['Instalación de sistema split 24000 BTU', 'MEDIA', 'PENDIENTE_DE_CIERRE', 'INSTALACION', 2],
    ['Temperatura inestable en sala de reuniones', 'ALTA', 'ABIERTA', 'REPARACION', 3],
    ['Revisión de unidades condensadoras', 'BAJA', 'ABIERTA', 'MANTENIMIENTO', 4],
    ['Ajuste de presión y carga de refrigerante', 'MEDIA', 'ABIERTA', 'REPARACION', 5],
  ].map(([descripcion, prioridad, estado, tipo_servicio, clientIndex], i) => ({
    orden_id: id(i + 41), descripcion, prioridad, estado, tipo_servicio,
    cliente_id: clients[clientIndex].cliente_id, tenant_id: tenant,
    creada_en: dateOf(-6 + i, 13), requiere_revisita: false,
  }));
  const visits = [
    [0, 0, 9, 0, 'EN_ATENCION'], [1, 1, 11, 0, 'PROGRAMADA'],
    [2, 2, 15, 0, 'FINALIZADA'], [3, 3, 8, 30, 'PROGRAMADA'],
    [4, 0, 14, 0, 'PROGRAMADA'], [5, 1, 10, 0, 'PROGRAMADA'],
  ].map(([orderIndex, techIndex, hour, minute, estado], i) => ({
    visita_id: id(i + 61), orden_id: orders[orderIndex].orden_id, tecnico_id: technicians[techIndex].tecnico_id,
    tenant_id: tenant, estado, inicio: dateOf(i === 0 ? 0 : Math.floor(i / 2), hour, minute),
    fin: dateOf(i === 0 ? 0 : Math.floor(i / 2), hour + 1, minute), version: 2,
  }));
  return { clients, technicians, orders, visits };
}
export function demoSession(tenant) {
  return {
    demo: true, token: '',
    usuario: { usuario_id: id(999), tenant_id: tenant, rol: 'ADMIN', email: 'demo@trazora.test', estado: 'ACTIVO' },
  };
}
