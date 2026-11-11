const MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre',
  'octubre', 'noviembre', 'diciembre']

export function clp(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  const texto = Math.abs(Math.trunc(n)).toLocaleString('es-CL')
  return `${n < 0 ? '-' : ''}$${texto}`
}

export function delta(n: number): string {
  if (n === 0) return 'sin cambio'
  return `${n > 0 ? '+' : ''}${clp(n)}`
}

export function mes(periodo: string | null | undefined): string {
  if (!periodo) return '—'
  const [anio, numero] = periodo.split('-')
  const nombre = MESES[Number(numero) - 1]
  return nombre ? `${nombre} ${anio}` : periodo
}

/** «septiembre y octubre 2026»; con años distintos, cada mes lleva el suyo. */
export function meses(periodos: string[]): string {
  const nombres = periodos.map((p) => mes(p).split(' '))
  const mismoAnio = new Set(nombres.map(([, anio]) => anio)).size === 1
  const partes = nombres.map(([m, anio]) => (mismoAnio ? m : `${m} ${anio}`))
  const texto = partes.length > 1 ? `${partes.slice(0, -1).join(', ')} y ${partes[partes.length - 1]}` : partes[0]
  return mismoAnio ? `${texto} ${nombres[0][1]}` : texto
}

export function hora(instante: string | null | undefined): string {
  if (!instante) return ''
  const fecha = new Date(instante)
  if (Number.isNaN(fecha.getTime())) return ''
  return fecha.toLocaleString('es-CL', {
    timeZone: 'America/Santiago', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit',
  })
}

export function titulo(texto: string): string {
  return texto ? texto[0].toUpperCase() + texto.slice(1) : texto
}
