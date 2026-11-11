import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { CheckCircle2, Download, FilePlus2, Pencil, Plus, Send, Trash2, X } from 'lucide-react'
import { useCallback, useState } from 'react'
import { toast } from 'sonner'

import Magia, { type FaseMagia } from '../../components/Magia'
import { Boton, Cargando, Cifra, cn, Entrada, estiloBoton, Etiqueta, Rotulo, Segmentos, Selector, Tarjeta, Texto,
  Vacio } from '../../components/ui'
import { api, type Borrador, type Diff, type ItemBandeja } from '../../lib/api'
import { clp, delta, hora, meses } from '../../lib/formato'
import { DiffTecnico, EnSimple } from './DiffVista'

type Modo = 'simple' | 'lado' | 'tecnico'

const sinMovimiento = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches

export default function Propuesta({ item, grupo }: { item: ItemBandeja; grupo?: ItemBandeja[] }) {
  const id = `B-${item.worker_id}-${item.periodo}`
  const { data: borradores, isLoading } = useQuery({ queryKey: ['borradores'], queryFn: api.borradores })
  const { data: caso } = useQuery({ queryKey: ['caso', item.caso_id], queryFn: () => api.caso(item.caso_id!),
    enabled: !!item.caso_id })
  const borrador = borradores?.find((b) => b.id === id)
  // Los otros meses del mismo error que todavía no tienen una propuesta abierta.
  const otros = (grupo ?? []).filter((m) => m.id !== item.id && m.estado === 'pendiente'
    && !borradores?.some((b) => b.id === `B-${m.worker_id}-${m.periodo}` && b.estado === 'borrador'))
    .map((m) => m.periodo!)

  if (isLoading) return <Cargando />
  if (!borrador || (borrador.estado === 'emitida' && caso?.hay_diferencias)) {
    return <Generar item={item} hayEmitida={!!borrador} otros={otros} />
  }
  return (
    <div className="space-y-5">
      {otros.length > 0 && <GenerarOtros item={item} periodos={otros} />}
      <ConBorrador key={`${borrador.id}-${borrador.version}-${borrador.estado}`} borrador={borrador} />
    </div>
  )
}

function GenerarOtros({ item, periodos }: { item: ItemBandeja; periodos: string[] }) {
  const cliente = useQueryClient()
  const generar = useMutation({
    mutationFn: () => Promise.all(periodos.map((p) => api.generarBorrador(item.worker_id, p))),
    onSuccess: () => {
      cliente.invalidateQueries({ queryKey: ['borradores'] })
      toast.success(`Propuesta generada para ${meses(periodos)}.`)
    },
    onError: (e) => toast.error(e.message),
  })
  return (
    <p className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-transparent bg-amber-50 px-3 py-2 text-sm text-amber-900
      ring-1 ring-amber-200">
      <span>El mismo error sigue sin propuesta en {meses(periodos)}.</span>
      <Boton cargando={generar.isPending} onClick={() => generar.mutate()}>
        <FilePlus2 className="size-4" />Generar también {meses(periodos)}
      </Boton>
    </p>
  )
}

function Generar({ item, hayEmitida, otros }: { item: ItemBandeja; hayEmitida: boolean; otros: string[] }) {
  const cliente = useQueryClient()
  const [magia, setMagia] = useState<{ fase: FaseMagia; borrador?: Borrador } | null>(null)
  const generar = useMutation({
    mutationFn: async () => {
      const [borrador] = await Promise.all([
        api.generarBorrador(item.worker_id, item.periodo!),
        ...otros.map((p) => api.generarBorrador(item.worker_id, p)),
        new Promise((listo) => setTimeout(listo, sinMovimiento() ? 0 : 1800)),
      ])
      return borrador as Borrador
    },
    onMutate: () => setMagia({ fase: 'varita' }),
    onSuccess: (borrador) => setMagia({ fase: 'conejo', borrador }),
    onError: (e) => {
      setMagia(null)
      toast.error(e.message)
    },
  })
  // Al refrescar los borradores esta vista se reemplaza por la propuesta: se hace al cerrar la animación.
  const ver = useCallback(() => {
    setMagia(null)
    cliente.invalidateQueries({ queryKey: ['borradores'] })
    toast.success(otros.length ? `Propuestas generadas para ${meses([item.periodo!, ...otros].sort())}.`
      : 'Propuesta generada como borrador.')
  }, [cliente, otros, item.periodo])
  return (
    <Tarjeta>
      {magia && <Magia fase={magia.fase} borrador={magia.borrador} onVer={ver} />}
      <Vacio icono={<FilePlus2 className="size-10" />}
        titulo={hayEmitida ? 'La corrección emitida ya no cuadra' : 'Todavía no hay una liquidación corregida'}>
        El motor recalcula la liquidación con el contrato vigente y los valores legales del mes. Queda como
        borrador: puedes ajustarla, revisar cada cambio y recién ahí emitirla.
      </Vacio>
      <div className="flex justify-center pb-4">
        <Boton variante="primario" cargando={generar.isPending} onClick={() => generar.mutate()}>
          <FilePlus2 className="size-4" />
          {otros.length ? `Generar propuestas de ${meses([item.periodo!, ...otros].sort())}` : 'Generar propuesta corregida'}
        </Boton>
      </div>
    </Tarjeta>
  )
}

function ConBorrador({ borrador }: { borrador: Borrador }) {
  const [base, setBase] = useState('emitida')
  const [modo, setModo] = useState<Modo>('simple')
  const [editando, setEditando] = useState(false)
  const [emitiendo, setEmitiendo] = useState(false)
  const emitida = borrador.estado === 'emitida'
  const { data: diff, isLoading } = useQuery({
    queryKey: ['diff', borrador.id, borrador.version, base],
    queryFn: () => api.diff(borrador.id, base),
  })
  const diferencia = borrador.propuesta.liquido_a_pagar - borrador.original.liquido_a_pagar
  const versiones = Array.from({ length: borrador.version - 1 }, (_, i) => borrador.version - 1 - i)

  return (
    <div className="space-y-5">
      <Tarjeta>
        <div className="flex flex-wrap items-center gap-x-8 gap-y-4">
          <Cifra etiqueta="Líquido emitido" valor={clp(borrador.original.liquido_a_pagar)} />
          <Cifra etiqueta={emitida ? 'Líquido rectificado' : 'Líquido propuesto'} valor={clp(borrador.propuesta.liquido_a_pagar)}
            detalle={delta(diferencia)} tono={diferencia > 0 ? 'verde' : diferencia < 0 ? 'rojo' : undefined} />
          <div className="space-y-1">
            <Etiqueta tono={emitida ? 'verde' : 'ambar'}>{emitida ? `Emitida · v${borrador.version}` : `Borrador v${borrador.version}`}</Etiqueta>
            <p className="text-xs text-slate-500">
              {emitida ? `Emitida por ${borrador.autor ?? 'RR.HH.'} · ${hora(borrador.emitido)}`
                : `Última versión de ${borrador.autor ?? 'RR.HH.'} · ${hora(borrador.actualizado)}`}
            </p>
          </div>
          <div className="ml-auto flex flex-wrap gap-2">
            <a href={api.urlPdf(borrador.id)} target="_blank" rel="noreferrer" className={estiloBoton()}>
              <Download className="size-4" />{emitida ? 'PDF' : 'PDF borrador'}
            </a>
            {!emitida && (
              <>
                <Boton onClick={() => setEditando((v) => !v)}><Pencil className="size-4" />Ajustar haberes</Boton>
                <Boton variante="primario" onClick={() => setEmitiendo(true)}><Send className="size-4" />Emitir v{borrador.version}</Boton>
              </>
            )}
          </div>
        </div>
        {!emitida && (
          <p className="mt-4 text-xs text-slate-500">
            Emitir esta versión cierra la diferencia: la decisión queda como Corregir.
          </p>
        )}
        {emitida && (
          <p className="mt-4 flex items-center gap-2 rounded-lg bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
            <CheckCircle2 className="size-4" />Es la liquidación vigente del trabajador. {borrador.nota}
          </p>
        )}
      </Tarjeta>

      {editando && <EditorHaberes borrador={borrador} onListo={() => setEditando(false)} />}

      <Tarjeta
        titulo="Qué cambia"
        accion={
          <div className="flex items-center gap-2">
            <Selector value={base} onChange={(e) => setBase(e.target.value)} className="w-auto py-1 text-xs">
              <option value="emitida">vs. liquidación emitida</option>
              {versiones.map((v) => <option key={v} value={String(v)}>vs. propuesta v{v}</option>)}
            </Selector>
            <Segmentos<Modo> valor={modo} onCambio={setModo} opciones={[
              { id: 'simple', texto: 'En simple' }, { id: 'lado', texto: 'Lado a lado' }, { id: 'tecnico', texto: 'Técnico' },
            ]} />
          </div>
        }
      >
        {isLoading || !diff ? <Cargando /> : (
          <div className={cn(modo === 'lado' && 'grid gap-6 xl:grid-cols-2')}>
            {modo !== 'tecnico' && <EnSimple diff={diff} />}
            {modo !== 'simple' && <DiffTecnico diff={diff} />}
          </div>
        )}
      </Tarjeta>

      {emitiendo && diff && <Emitir borrador={borrador} diff={base === 'emitida' ? diff : undefined}
        onCerrar={() => setEmitiendo(false)} />}
    </div>
  )
}

interface Fila {
  concepto: string
  tipo: 'imponible' | 'no_imponible'
  monto: number
}

function EditorHaberes({ borrador, onListo }: { borrador: Borrador; onListo: () => void }) {
  const cliente = useQueryClient()
  const [filas, setFilas] = useState<Fila[]>([
    ...borrador.propuesta.haberes_imponibles.map((h) => ({ ...h, tipo: 'imponible' as const })),
    ...borrador.propuesta.haberes_no_imponibles.map((h) => ({ ...h, tipo: 'no_imponible' as const })),
  ])
  const [motivo, setMotivo] = useState('')
  const guardar = useMutation({
    mutationFn: () => {
      const validas = filas.filter((f) => f.concepto.trim())
      return api.ajustarBorrador(
        borrador.id,
        validas.filter((f) => f.tipo === 'imponible').map(({ concepto, monto }) => ({ concepto: concepto.trim(), monto })),
        validas.filter((f) => f.tipo === 'no_imponible').map(({ concepto, monto }) => ({ concepto: concepto.trim(), monto })),
        motivo)
    },
    onSuccess: (nuevo) => {
      cliente.invalidateQueries({ queryKey: ['borradores'] })
      cliente.invalidateQueries({ queryKey: ['historial', borrador.id] })
      toast.success(`Guardado como v${nuevo.version}. Los descuentos legales se recalcularon.`)
      onListo()
    },
    onError: (e) => toast.error(e.message),
  })
  const cambiar = (i: number, cambio: Partial<Fila>) =>
    setFilas((actual) => actual.map((f, j) => (j === i ? { ...f, ...cambio } : f)))

  return (
    <Tarjeta titulo="Ajustar haberes" accion={<Boton variante="fantasma" onClick={onListo}><X className="size-4" /></Boton>}>
      <p className="mb-3 text-xs text-slate-500">
        Cambia montos o agrega conceptos. Los descuentos legales (AFP, salud, cesantía, impuesto) los vuelve a calcular el motor.
        Guardar crea una versión nueva.
      </p>
      <table className="w-full text-sm">
        <thead className="text-left text-xs text-slate-500">
          <tr><th className="pb-2 font-medium">Concepto</th><th className="pb-2 font-medium">Tipo</th>
            <th className="pb-2 text-right font-medium">Monto</th><th /></tr>
        </thead>
        <tbody>
          {filas.map((f, i) => (
            <tr key={i}>
              <td className="py-1 pr-2"><Entrada value={f.concepto} onChange={(e) => cambiar(i, { concepto: e.target.value })} /></td>
              <td className="w-40 py-1 pr-2">
                <Selector value={f.tipo} onChange={(e) => cambiar(i, { tipo: e.target.value as Fila['tipo'] })}>
                  <option value="imponible">Imponible</option>
                  <option value="no_imponible">No imponible</option>
                </Selector>
              </td>
              <td className="w-40 py-1 pr-2">
                <Entrada type="number" min={0} step={1} value={f.monto} className="text-right tabular-nums"
                  onChange={(e) => cambiar(i, { monto: Math.max(0, Math.trunc(Number(e.target.value) || 0)) })} />
              </td>
              <td className="w-8 py-1">
                <button onClick={() => setFilas((a) => a.filter((_, j) => j !== i))} className="text-slate-400 hover:text-rose-600"
                  title="Quitar concepto"><Trash2 className="size-4" /></button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <Boton variante="fantasma" className="mt-2"
        onClick={() => setFilas((a) => [...a, { concepto: '', tipo: 'imponible', monto: 0 }])}>
        <Plus className="size-4" />Agregar concepto
      </Boton>
      <div className="mt-4 flex items-end gap-3">
        <div className="flex-1">
          <Rotulo texto="Motivo del ajuste" ayuda="Aparece en la bitácora, en el PDF y en la vista simple.">
            <Entrada value={motivo} onChange={(e) => setMotivo(e.target.value)} placeholder="Ej.: bono especial aprobado por jefatura" />
          </Rotulo>
        </div>
        <Boton variante="primario" cargando={guardar.isPending} onClick={() => guardar.mutate()} className="mb-5">
          Guardar como v{borrador.version + 1}
        </Boton>
      </div>
    </Tarjeta>
  )
}

function Emitir({ borrador, diff, onCerrar }: { borrador: Borrador; diff?: Diff; onCerrar: () => void }) {
  const cliente = useQueryClient()
  const [revisado, setRevisado] = useState(false)
  const [nota, setNota] = useState('')
  const { data: contraEmitida } = useQuery({
    queryKey: ['diff', borrador.id, borrador.version, 'emitida'],
    queryFn: () => api.diff(borrador.id, 'emitida'),
    initialData: diff,
  })
  const emitir = useMutation({
    mutationFn: () => api.emitirBorrador(borrador.id, nota.trim(), borrador.version),
    onSuccess: () => {
      ;['borradores', 'bandeja', 'caso', 'historial'].forEach((k) => cliente.invalidateQueries({ queryKey: [k] }))
      toast.success(`Liquidación v${borrador.version} emitida. Ya es la vigente.`)
      onCerrar()
    },
    onError: (e) => toast.error(e.message),
  })
  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-slate-900/40 p-4" onClick={onCerrar}>
      <div className="max-h-[90vh] w-full max-w-2xl overflow-y-auto overscroll-contain rounded-2xl border border-transparent bg-white shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <header className="flex items-center justify-between border-b border-slate-100 px-5 py-3">
          <h2 className="font-semibold">Emitir la versión v{borrador.version}</h2>
          <Boton variante="fantasma" onClick={onCerrar}><X className="size-4" /></Boton>
        </header>
        <div className="space-y-4 p-5">
          <p className="text-sm text-slate-600">
            Reemplaza a la liquidación vigente. La anterior queda guardada en la bitácora junto con tu nombre y la nota.
          </p>
          {contraEmitida ? <EnSimple diff={contraEmitida} /> : <Cargando />}
          <label className="flex cursor-pointer items-start gap-2.5 rounded-lg border border-transparent bg-amber-50 p-3 text-sm ring-1 ring-amber-200">
            <input type="checkbox" checked={revisado} onChange={(e) => setRevisado(e.target.checked)} className="mt-0.5 accent-indigo-600" />
            Revisé los cambios de la versión v{borrador.version} contra la liquidación emitida.
          </label>
          <Rotulo texto="Nota de emisión">
            <Texto value={nota} onChange={(e) => setNota(e.target.value)}
              placeholder="Ej.: se aplica tope imponible y se devuelve la diferencia en la próxima remuneración." />
          </Rotulo>
        </div>
        <footer className="flex justify-end gap-2 border-t border-slate-100 px-5 py-3">
          <Boton onClick={onCerrar}>Cancelar</Boton>
          <Boton variante="primario" disabled={!revisado || !nota.trim()} cargando={emitir.isPending}
            onClick={() => emitir.mutate()}>
            <Send className="size-4" />Emitir liquidación
          </Boton>
        </footer>
      </div>
    </div>
  )
}
