import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, ArrowRight, Bot, CheckCircle2, Sparkles } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import Markdown from '../../components/Markdown'
import { Boton, Cargando, cn, Tarjeta, Texto } from '../../components/ui'
import { api, type Caso, type ItemBandeja } from '../../lib/api'
import { clp } from '../../lib/formato'

const DECISIONES = [
  { id: 'mantener', texto: 'Mantener', ayuda: 'La liquidación emitida está bien.' },
  { id: 'corregir', texto: 'Corregir', ayuda: 'Se prepara en la pestaña Liquidación corregida.' },
  { id: 'derivar', texto: 'Derivar', ayuda: 'Lo resuelve otra área (p. ej. legal).' },
] as const

export default function Diferencia({ casoId, onCorregir, grupo }: {
  casoId: string; onCorregir: () => void; grupo?: ItemBandeja[] }) {
  const { data: caso, isLoading } = useQuery({ queryKey: ['caso', casoId], queryFn: () => api.caso(casoId) })
  const [verCuadran, setVerCuadran] = useState(false)
  if (isLoading || !caso) return <Cargando />
  const diferencias = caso.lineas.filter((l) => l.estado === 'diferencia')
  const alineadas = caso.lineas.filter((l) => l.estado !== 'diferencia')

  return (
    <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_340px]">
      <div className="space-y-5">
        {caso.reabierto && (
          <p className="flex items-center gap-2 rounded-lg border border-transparent bg-amber-50 px-3 py-2 text-sm text-amber-800 ring-1 ring-amber-200">
            <AlertTriangle className="size-4" />Una carga nueva cambió las diferencias. El caso volvió a pendiente.
          </p>
        )}
        {!caso.hay_diferencias && (
          <p className="flex items-center gap-2 rounded-lg border border-transparent bg-emerald-50 px-3 py-2 text-sm text-emerald-800 ring-1 ring-emerald-200">
            <CheckCircle2 className="size-4" />Con la ficha vigente esta liquidación ya no tiene diferencias.
          </p>
        )}
        <Tarjeta titulo="Qué no cuadra">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-slate-500">
              <tr>
                <th className="pb-2 font-medium">Concepto</th>
                <th className="pb-2 pl-4 text-right font-medium">Esperado</th>
                <th className="pb-2 pl-4 text-right font-medium">Pagado</th>
                <th className="pb-2 pl-4 text-right font-medium">Diferencia</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {diferencias.map((l) => (
                <tr key={l.codigo} className="align-top">
                  <td className="py-2.5 pr-3">
                    <p className="font-medium text-slate-800">{l.concepto}</p>
                    {l.causa_probable && <p className="text-xs text-slate-500">{l.causa_probable}</p>}
                  </td>
                  <td className="py-2.5 pl-4 text-right whitespace-nowrap tabular-nums">{clp(l.esperado)}</td>
                  <td className="py-2.5 pl-4 text-right whitespace-nowrap tabular-nums">{clp(l.pagado)}</td>
                  <td className="py-2.5 pl-4 text-right font-semibold whitespace-nowrap tabular-nums text-rose-600">{clp(l.diferencia)}</td>
                </tr>
              ))}
              {verCuadran && alineadas.map((l) => (
                <tr key={l.codigo} className="text-slate-400">
                  <td className="py-2 pr-3">{l.concepto}</td>
                  <td className="py-2 pl-4 text-right whitespace-nowrap tabular-nums">{clp(l.esperado)}</td>
                  <td className="py-2 pl-4 text-right whitespace-nowrap tabular-nums">{clp(l.pagado)}</td>
                  <td className="py-2 pl-4 text-right text-xs">cuadra</td>
                </tr>
              ))}
            </tbody>
          </table>
          {alineadas.length > 0 && (
            <button type="button" onClick={() => setVerCuadran((v) => !v)}
              className="mt-2 text-xs text-slate-500 hover:text-slate-800">
              {verCuadran ? 'Ocultar lo que cuadra' : `${alineadas.length} conceptos cuadran`}
            </button>
          )}
        </Tarjeta>
        <Explicacion caso={caso} />
      </div>
      <Decision caso={caso} onCorregir={onCorregir} grupo={grupo} />
    </div>
  )
}

function Explicacion({ caso }: { caso: Caso }) {
  const cliente = useQueryClient()
  const explicar = useMutation({
    mutationFn: () => api.explicar(caso.id),
    onSuccess: (nuevo) => cliente.setQueryData(['caso', caso.id], nuevo),
    onError: (e) => toast.error(e.message),
  })
  const informe = caso.informe ?? {}
  return (
    <Tarjeta
      titulo={<span className="flex items-center gap-1.5"><Bot className="size-4 text-violet-600" />Explicación del agente</span>}
      accion={
        <Boton variante="fantasma" cargando={explicar.isPending} onClick={() => explicar.mutate()}>
          <Sparkles className="size-4" />{informe.respuesta ? 'Volver a explicar' : 'Pedir explicación'}
        </Boton>
      }
    >
      {explicar.isPending ? <Cargando texto="El agente está revisando la liquidación…" />
        : informe.respuesta ? <div className="text-sm leading-relaxed text-slate-700"><Markdown texto={informe.respuesta} /></div>
          : informe.error ? <p className="text-sm text-rose-600">{informe.error}</p>
            : <p className="text-sm text-slate-500">Todavía no hay una explicación guardada para este caso.</p>}
    </Tarjeta>
  )
}

function Decision({ caso, onCorregir, grupo }: { caso: Caso; onCorregir: () => void; grupo?: ItemBandeja[] }) {
  const cliente = useQueryClient()
  const [estado, setEstado] = useState(caso.estado === 'pendiente' ? 'mantener' : caso.estado)
  const [nota, setNota] = useState(caso.nota ?? '')
  const casos = grupo?.map((m) => m.caso_id).filter((id): id is string => !!id) ?? [caso.id]
  const decidir = useMutation({
    mutationFn: () => Promise.all(casos.map((id) => api.decidir(id, estado, nota))),
    onSuccess: (nuevos) => {
      nuevos.forEach((nuevo) => cliente.setQueryData(['caso', nuevo.id], nuevo))
      cliente.invalidateQueries({ queryKey: ['bandeja'] })
      toast.success(casos.length > 1 ? `Decisión registrada en los ${casos.length} meses.` : 'Decisión registrada.')
    },
    onError: (e) => toast.error(e.message),
  })
  return (
    <Tarjeta titulo="Decisión" className="h-fit xl:sticky xl:top-0">
      <form
        className="space-y-3"
        onSubmit={(e) => { e.preventDefault(); decidir.mutate() }}
      >
        <div className="space-y-1.5">
          {DECISIONES.map((d) => (
            <label key={d.id} className={cn('flex cursor-pointer gap-2.5 rounded-lg border border-transparent p-2.5 ring-1 transition-colors duration-150',
              estado === d.id ? 'bg-indigo-50 ring-indigo-300' : 'ring-slate-200 hover:bg-slate-50')}>
              <input type="radio" name="decision" checked={estado === d.id} onChange={() => setEstado(d.id)}
                className="mt-0.5 accent-indigo-600" />
              <span>
                <span className="block text-sm font-medium">{d.texto}</span>
                <span className="block text-xs text-slate-500">{d.ayuda}</span>
              </span>
            </label>
          ))}
        </div>
        {estado === 'corregir' ? (
          <>
            <p className="text-xs text-slate-500">
              {casos.length > 1
                ? `Se preparan las ${casos.length} liquidaciones corregidas de una vez. La decisión Corregir queda al emitir cada una.`
                : 'La nota y la decisión Corregir quedan registradas al emitir esa liquidación.'}
            </p>
            <Boton type="button" variante="primario" className="w-full" onClick={onCorregir}>
              Preparar la liquidación corregida<ArrowRight className="size-4" />
            </Boton>
          </>
        ) : (
          <>
            <Texto value={nota} onChange={(e) => setNota(e.target.value)} placeholder="Qué se revisó y qué se va a hacer." />
            <Boton type="submit" variante="primario" className="w-full" cargando={decidir.isPending} disabled={!nota.trim()}>
              {casos.length > 1 ? `Registrar en los ${casos.length} meses` : 'Registrar decisión'}
            </Boton>
          </>
        )}
      </form>
    </Tarjeta>
  )
}
