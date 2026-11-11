import type { ItemBandeja } from './api'
import { clp, mes } from './formato'

// Dos caminos dejan plata a favor del trabajador. Si escribió, manda la conversación:
// el agente puede haberlo marcado además al cargar.
export type Camino = 'agente' | 'conversacion'

export function caminoDe(item: ItemBandeja): Camino {
  return item.origen.includes('trabajador') ? 'conversacion' : 'agente'
}

export function relato(item: ItemBandeja): string {
  if (caminoDe(item) === 'agente') {
    return 'Nadie escribió. Al cargar la liquidación, el agente la comparó con el contrato vigente y con la ley del mes.'
  }
  const tambien = item.origen.includes('sistema')
    ? ' El agente lo confirmó al comparar la liquidación cargada.'
    : ''
  return `Partió porque ${item.nombre.split(' ')[0]} escribió. El agente respondió con su liquidación y dejó el caso en la bandeja.${tambien}`
}

/** Una línea. La causa y el detalle de cada mes viven en la pestaña Diferencia. */
export function relatoRepeticion(miembros: ItemBandeja[]): string {
  const grupo = miembros[0].grupo!
  const conceptos = grupo.conceptos.join(' y ').toLowerCase()
  const cuando = miembros.map((m) => mes(m.periodo).split(' ')[0])
  const lista = cuando.length > 1 ? `${cuando.slice(0, -1).join(', ')} y ${cuando.at(-1)}` : cuando[0]
  return `Lo mismo con ${conceptos} en ${lista}. En total ${clp(grupo.diferencia_total)}.`
}
