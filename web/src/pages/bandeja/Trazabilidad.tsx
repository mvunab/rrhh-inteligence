import { useQuery } from '@tanstack/react-query'
import { FilePlus2, FileSignature, History, Pencil, Replace } from 'lucide-react'

import { Cargando, cn, Tarjeta, Vacio } from '../../components/ui'
import { api, type Evento, type ItemBandeja } from '../../lib/api'
import { clp, delta, hora } from '../../lib/formato'

const ACCIONES: Record<string, { texto: string; icono: typeof History; color: string }> = {
  propuesta_generada: { texto: 'Propuesta generada', icono: FilePlus2, color: 'bg-sky-100 text-sky-700' },
  propuesta_ajustada: { texto: 'Propuesta ajustada', icono: Pencil, color: 'bg-amber-100 text-amber-700' },
  liquidacion_reemplazada: { texto: 'Liquidación vigente reemplazada', icono: Replace, color: 'bg-slate-200 text-slate-700' },
  liquidacion_emitida: { texto: 'Liquidación emitida', icono: FileSignature, color: 'bg-emerald-100 text-emerald-700' },
}

const ORIGEN: Record<string, string> = {
  base: 'carga inicial', excel: 'Excel', pdf: 'PDF', rectificada: 'rectificación', buk: 'Buk',
}

function detalle(e: Evento): string {
  const d = e.datos
  switch (e.accion) {
    case 'propuesta_generada':
      return d.reemplaza_version
        ? `Reemplaza la v${d.reemplaza_version} (${d.estado_previo === 'emitida' ? 'ya emitida' : 'borrador'}) porque la ficha o la liquidación cambiaron.`
        : 'El motor recalculó la liquidación con la ficha vigente.'
    case 'propuesta_ajustada':
      return [d.nota, d.cambios?.length ? `Cambia: ${d.cambios.map((c) => c.concepto).join(', ')}.` : '']
        .filter(Boolean).join(' ')
    case 'liquidacion_reemplazada':
      return `La liquidación de ${ORIGEN[d.origen_anterior ?? ''] ?? d.origen_anterior} (${clp(d.anterior?.liquido_a_pagar)})`
        + ` quedó reemplazada por una de ${ORIGEN[d.origen_nuevo ?? ''] ?? 'otra fuente'}`
        + ` (${clp(d.nueva?.liquido_a_pagar)}).`
    case 'liquidacion_emitida':
      return [d.nota, d.liquido_anterior != null && d.liquido != null
        ? `El líquido pasa de ${clp(d.liquido_anterior)} a ${clp(d.liquido)} (${delta(d.liquido - d.liquido_anterior)}).` : '']
        .filter(Boolean).join(' ')
    default:
      return ''
  }
}

export default function Trazabilidad({ item }: { item: ItemBandeja }) {
  const id = `B-${item.worker_id}-${item.periodo}`
  const { data: eventos, isLoading } = useQuery({ queryKey: ['historial', id], queryFn: () => api.historial(id) })
  if (isLoading) return <Cargando />
  if (!eventos?.length) {
    return <Vacio icono={<History className="size-10" />} titulo="Sin movimientos todavía">
      Cuando generes, ajustes o emitas una liquidación corregida, cada paso queda registrado aquí con su autor.
    </Vacio>
  }
  return (
    <Tarjeta titulo={`Bitácora · ${eventos.length} ${eventos.length === 1 ? 'evento' : 'eventos'}`}>
      <ol className="relative space-y-5 before:absolute before:top-2 before:bottom-2 before:left-4 before:w-px before:bg-slate-200">
        {[...eventos].reverse().map((e) => {
          const a = ACCIONES[e.accion] ?? { texto: e.accion, icono: History, color: 'bg-slate-100 text-slate-600' }
          return (
            <li key={e.id} className="relative flex gap-3">
              <span className={cn('z-10 grid size-8 shrink-0 place-items-center rounded-full ring-4 ring-white', a.color)}>
                <a.icono className="size-4" />
              </span>
              <div className="min-w-0 flex-1 pt-0.5">
                <p className="text-sm">
                  <span className="font-medium text-slate-900">{a.texto}</span>
                  {e.datos.version != null && <span className="text-slate-500"> · v{e.datos.version}</span>}
                  {e.datos.liquido != null && e.accion !== 'liquidacion_reemplazada' &&
                    <span className="text-slate-500"> · líquido {clp(e.datos.liquido)}</span>}
                </p>
                <p className="text-xs text-slate-400">{e.autor} · {hora(e.cuando)}</p>
                {detalle(e) && <p className="mt-1 text-sm text-slate-600">{detalle(e)}</p>}
              </div>
            </li>
          )
        })}
      </ol>
    </Tarjeta>
  )
}
