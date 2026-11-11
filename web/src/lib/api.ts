// Cliente de la API de RRHH Intelligence. El navegador habla con /api; nginx o Vite lo mandan a FastAPI.
import { guardarToken, leerToken } from './sesion'

const BASE = '/api'

export class ErrorApi extends Error {
  status?: number
  constructor(mensaje: string, status?: number) {
    super(mensaje)
    this.status = status
  }
}

async function pedir<T>(ruta: string, init: RequestInit = {}, conAuth = true): Promise<T> {
  const headers = new Headers(init.headers)
  if (conAuth) {
    const token = leerToken()
    if (token) headers.set('Authorization', `Bearer ${token}`)
  }
  let respuesta: Response
  try {
    respuesta = await fetch(`${BASE}${ruta}`, { ...init, headers })
  } catch {
    throw new ErrorApi('La API no responde.')
  }
  if (respuesta.status === 401 && conAuth) {
    guardarToken(null)
    if (!window.location.pathname.startsWith('/login')) {
      window.location.assign('/login')
    }
    throw new ErrorApi('Debes iniciar sesión.', 401)
  }
  if (!respuesta.ok) {
    let detalle: unknown
    try {
      detalle = (await respuesta.json()).detail
    } catch {
      detalle = respuesta.statusText
    }
    const texto = Array.isArray(detalle)
      ? detalle.map((d: { msg?: string }) => d.msg ?? String(d)).join('; ')
      : String(detalle ?? respuesta.status)
    throw new ErrorApi(texto, respuesta.status)
  }
  if (respuesta.status === 204) return undefined as T
  const tipo = respuesta.headers.get('content-type') ?? ''
  return (tipo.includes('application/json') ? respuesta.json() : respuesta.blob()) as Promise<T>
}

const json = (metodo: string, cuerpo: unknown): RequestInit => ({
  method: metodo,
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(cuerpo),
})

// ------------------------------------------------------------------ tipos
export type Tipo = 'diferencia' | 'revision'
export type Severidad = 'critico' | 'revisar' | 'sin diferencias'

export interface Mensaje {
  texto: string
  creado: string
  agente?: string
}

export interface Solicitud {
  id: string
  worker_id: string
  area: string
  tipo: Tipo
  periodo: string | null
  pregunta: string
  mensajes: Mensaje[]
  motivos: ('trabajador' | 'agente')[]
  resumen: string
  estado: 'propuesta' | 'pendiente' | 'respondida'
  respuesta: string
  creado: string
  respondido: string | null
  respondido_por?: string | null
}

export interface ItemBandeja {
  id: string
  worker_id: string
  nombre: string
  area: string
  periodo: string | null
  tipo: Tipo
  origen: ('trabajador' | 'sistema')[]
  estado: 'pendiente' | 'resuelta'
  severidad: Severidad
  diferencia_total: number
  decision: string | null
  caso_id: string | null
  solicitudes: Solicitud[]
  grupo: Grupo | null
}

/** El mismo error del mismo trabajador en varios meses. */
export interface Grupo {
  id: string
  periodos: string[]
  casos: string[]
  conceptos: string[]
  causa: string | null
  diferencia_total: number
  pendientes: number
}

export interface LineaCaso {
  codigo: string
  concepto: string
  esperado: number
  pagado: number
  diferencia: number
  estado: 'diferencia' | 'ok' | string
  causa_probable: string | null
}

export interface Caso {
  id: string
  worker_id: string
  periodo: string
  estado: 'pendiente' | 'mantener' | 'corregir' | 'derivar'
  nota: string
  lineas: LineaCaso[]
  hay_diferencias: boolean
  diferencia_total: number
  severidad: Severidad
  reabierto: boolean
  informe: { respuesta?: string; error?: string } | null
}

export interface Haber {
  concepto: string
  monto: number
}

export interface Descuento extends Haber {
  codigo: string
  base?: number
  tasa?: number | null
  institucion?: string
}

export interface Liquidacion {
  worker_id: string
  periodo: string
  haberes_imponibles: Haber[]
  haberes_no_imponibles: Haber[]
  descuentos_legales: Descuento[]
  total_haberes: number
  total_descuentos: number
  liquido_a_pagar: number
}

export interface Ajuste {
  concepto: string
  emitido: number
  propuesto: number
  diferencia: number
  motivo: string
}

export interface Borrador {
  id: string
  worker_id: string
  periodo: string
  version: number
  estado: 'borrador' | 'emitida'
  autor?: string
  nota: string
  original: Liquidacion
  propuesta: Liquidacion
  ajustes: Ajuste[]
  creado: string
  actualizado: string
  emitido: string | null
  trabajador: { nombre?: string }
}

export interface PuntoSimple {
  texto: string
  por_que: string
  favorece_al_trabajador: boolean
}

export interface Diff {
  texto: string
  cambios: { seccion: string; concepto: string; antes: number | null; despues: number | null }[]
  diferencia_liquido: number
  etiquetas: [string, string]
  en_simple: {
    titular: string
    liquido_antes: number
    liquido_despues: number
    puntos: PuntoSimple[]
    pie: string
  }
}

export interface Evento {
  id: number
  accion: string
  autor: string
  cuando: string
  datos: {
    version?: number
    liquido?: number
    nota?: string
    cambios?: { concepto: string }[]
    reemplaza_version?: number
    estado_previo?: string
    anterior?: Liquidacion
    nueva?: Liquidacion
    origen_anterior?: string
    origen_nuevo?: string
    liquido_anterior?: number
  }
}

export interface FilaSector {
  area: string
  trabajadores: number
  solicitudes: number
  diferencias: number
  revisiones: number
  pendientes: number
}

export interface Trabajador {
  worker_id: string
  nombre: string
  cargo: string
  area: string
}

export interface LiquidacionResumen {
  worker_id: string
  periodo: string
  liquido_a_pagar: number
  origen: string
}

export interface ContratoVigente {
  worker_id: string
  nombre: string
  ficha: { afp: string; salud: string; tipo_contrato: string; sueldo_base: number; fecha_termino: string | null }
  vigente_desde: string | null
  origen: string
  anexos: { vigente_desde: string; descripcion: string; cambios: Record<string, unknown>; origen: string }[]
}

export interface Conector {
  nombre: string
  disponible: boolean
  detalle: string
  modo: 'api' | 'demo' | null
}

export interface SincronizacionBuk {
  periodo: string
  modo: 'api' | 'demo'
  trabajadores: number
  liquidaciones: number
  altas: { worker_id: string; nombre: string }[]
  actualizados: { worker_id: string; nombre: string; cambios: Record<string, [unknown, unknown]> }[]
  casos: string[]
  resumen: string
}

export interface Analista {
  id: string
  email: string
  nombre: string
  cargo: string
  area: string
  telefono: string
  avatar: string | null
  creado: string | null
}

export interface DocumentoCompartido {
  documento: string
  tipo: string
  origen: string
  descripcion: string
  cargado: string | null
}

export interface DocumentoContrato {
  documento: string
  tipo: 'contrato' | 'anexo' | string
  origen: string
  vigente_desde: string | null
  descripcion: string
  cambios: Record<string, unknown>
  cargado: string | null
  contenido: string
}

export interface PropuestaCampo {
  valor: string | number | null
  evidencia: string
  confianza: 'alta' | 'media' | 'baja'
}

export interface VistaFicha {
  afp: string | null
  salud: string | null
  tipo_contrato: string | null
  fecha_termino: string | null
  jornada: string | null
  sueldo_base: number | null
  colacion: number | null
  movilizacion: number | null
  asignacion_turno: number | null
  bono_monto: number | null
  bono_meta_atenciones: number | null
}

export interface PreviewDescuentos {
  imponible: number
  total: number
  lineas: { codigo: string; concepto: string; monto: number }[]
}

export interface LecturaDocumento {
  kind: 'contrato' | 'anexo'
  worker_id: string
  vigente_desde: string
  descripcion: string
  texto: string
  propuesta: {
    resumen: string
    campos_no_mapeados: string[]
    afp?: PropuestaCampo | null
    salud?: PropuestaCampo | null
    tipo_contrato?: PropuestaCampo | null
    fecha_termino?: PropuestaCampo | null
    jornada?: PropuestaCampo | null
    sueldo_base?: PropuestaCampo | null
    colacion?: PropuestaCampo | null
    movilizacion?: PropuestaCampo | null
    asignacion_turno?: PropuestaCampo | null
    bono_monto?: PropuestaCampo | null
    bono_meta_atenciones?: PropuestaCampo | null
  }
  cambios_sugeridos: Record<string, string | number>
  ficha_actual: VistaFicha
  ficha_propuesta: VistaFicha
  preview_descuentos: { actual: PreviewDescuentos; propuesta: PreviewDescuentos }
}

// ------------------------------------------------------------------ llamadas
export const api = {
  login: (email: string, password: string) =>
    pedir<{ token: string; analista: Analista }>('/auth/login', json('POST', { email, password }), false),
  logout: () => pedir<{ ok: boolean }>('/auth/logout', { method: 'POST' }),
  yo: () => pedir<Analista>('/auth/me'),
  actualizarPerfil: (datos: Partial<Pick<Analista, 'nombre' | 'cargo' | 'area' | 'telefono'>>) =>
    pedir<Analista>('/auth/me', json('PUT', datos)),
  subirAvatar: (archivo: File) => {
    const datos = new FormData()
    datos.append('archivo', archivo)
    return pedir<Analista>('/auth/me/avatar', { method: 'PUT', body: datos })
  },

  bandeja: () => pedir<ItemBandeja[]>('/bandeja'),
  caso: (id: string) => pedir<Caso>(`/casos/${id}`),
  decidir: (id: string, estado: string, nota: string) =>
    pedir<Caso>(`/casos/${id}/decision`, json('POST', { estado, nota })),
  explicar: (id: string) => pedir<Caso>(`/casos/${id}/explicacion`, { method: 'POST' }),
  responder: (solicitudId: string, respuesta: string) =>
    pedir<Solicitud>(`/solicitudes/${solicitudId}/respuesta`, json('POST', { respuesta })),

  borradores: () => pedir<Borrador[]>('/borradores'),
  generarBorrador: (worker_id: string, periodo: string) =>
    pedir<Borrador>('/borradores', json('POST', { worker_id, periodo })),
  ajustarBorrador: (id: string, imponibles: Haber[], noImponibles: Haber[], nota: string) =>
    pedir<Borrador>(`/borradores/${id}`, json('PUT', {
      haberes_imponibles: imponibles, haberes_no_imponibles: noImponibles, nota,
    })),
  emitirBorrador: (id: string, nota: string, version: number) =>
    pedir<Borrador>(`/borradores/${id}/emision`, json('POST', { nota, version })),
  historial: (id: string) => pedir<Evento[]>(`/borradores/${id}/historial`),
  diff: (id: string, base: string) => pedir<Diff>(`/borradores/${id}/diff?base=${encodeURIComponent(base)}`),
  urlPdf: (id: string) => {
    const token = leerToken()
    const q = token ? `?token=${encodeURIComponent(token)}` : ''
    return `${BASE}/borradores/${id}/pdf${q}`
  },

  estadisticas: () => pedir<FilaSector[]>('/estadisticas/solicitudes'),
  trabajadores: () => pedir<Trabajador[]>('/trabajadores'),
  liquidaciones: () => pedir<LiquidacionResumen[]>('/liquidaciones'),
  contratos: () => pedir<ContratoVigente[]>('/contratos'),
  documentosContrato: (workerId: string) =>
    pedir<DocumentoContrato[]>(`/trabajadores/${encodeURIComponent(workerId)}/documentos-contrato`),
  documentosCompartidos: () => pedir<DocumentoCompartido[]>('/documentos-compartidos'),
  conectores: () => pedir<Conector[]>('/conectores'),
  urlPlantilla: () => {
    const token = leerToken()
    const q = token ? `?token=${encodeURIComponent(token)}` : ''
    return `${BASE}/plantilla/liquidaciones.xlsx${q}`
  },
  urlContratoPdf: (workerId: string) => {
    const token = leerToken()
    const q = token ? `?token=${encodeURIComponent(token)}` : ''
    return `${BASE}/trabajadores/${encodeURIComponent(workerId)}/contrato.pdf${q}`
  },
  sincronizarBuk: (periodo: string) => pedir<SincronizacionBuk>('/cargas/buk', json('POST', { periodo })),

  leerContrato: (archivo: File, workerId: string, vigenteDesde: string) => {
    const datos = new FormData()
    datos.append('worker_id', workerId)
    datos.append('vigente_desde', vigenteDesde)
    datos.append('archivo', archivo)
    return pedir<LecturaDocumento>('/cargas/contrato/leer', { method: 'POST', body: datos })
  },
  leerAnexo: (archivo: File, workerId: string, vigenteDesde: string, descripcion: string) => {
    const datos = new FormData()
    datos.append('worker_id', workerId)
    datos.append('vigente_desde', vigenteDesde)
    datos.append('descripcion', descripcion)
    datos.append('archivo', archivo)
    return pedir<LecturaDocumento>('/cargas/anexo/leer', { method: 'POST', body: datos })
  },

  cargarArchivo: (ruta: string, archivo: File, campos: Record<string, string> = {}) => {
    const datos = new FormData()
    Object.entries(campos).forEach(([k, v]) => datos.append(k, v))
    datos.append('archivo', archivo)
    return pedir<{ resumen: string }>(ruta, { method: 'POST', body: datos })
  },
}
