import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Download, ExternalLink, FileSpreadsheet, FileText, PlugZap, RefreshCw, Sparkles, Upload, UserRound } from 'lucide-react'
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { toast } from 'sonner'

import { Boton, Cargando, Entrada, Etiqueta, Pestanas, Rotulo, Selector, Tarjeta } from '../components/ui'
import {
  api,
  type DocumentoContrato,
  type LecturaDocumento,
  type PropuestaCampo,
  type Trabajador,
  type VistaFicha,
} from '../lib/api'
import { clp, hora, mes } from '../lib/formato'

type VistaCarga = 'liquidaciones' | 'trabajador' | 'organizacionales'

const ORIGEN: Record<string, string> = {
  base: 'Sistema', migrado: 'Sistema', excel: 'Excel', pdf: 'PDF', rectificada: 'Rectificada', buk: 'Buk',
}
const AFP = ['Uno', 'Modelo', 'PlanVital', 'Habitat', 'Capital', 'Cuprum', 'ProVida']
const CAMPOS: Record<string, string> = {
  afp: 'AFP', salud: 'salud', tipo_contrato: 'contrato', sueldo_base: 'sueldo base', bono_monto: 'bono',
  bono_meta_atenciones: 'meta', asignacion_turno: 'asignación de turno',
}

function useCarga(ruta: string, invalidar: string[]) {
  const cliente = useQueryClient()
  return useMutation({
    mutationFn: ({ archivo, campos }: { archivo: File; campos?: Record<string, string> }) =>
      api.cargarArchivo(ruta, archivo, campos),
    onSuccess: (r) => {
      toast.success(r.resumen)
      invalidar.forEach((k) => cliente.invalidateQueries({ queryKey: [k] }))
    },
    onError: (e) => toast.error(e.message),
  })
}

function SubirArchivo({ acepta, texto, cargando, onArchivo }: {
  acepta: string; texto: string; cargando: boolean; onArchivo: (f: File) => void }) {
  const [archivo, setArchivo] = useState<File | null>(null)
  return (
    <div className="flex items-center gap-2">
      <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 rounded-lg border border-dashed border-slate-300
        px-3 py-2 text-sm text-slate-500 hover:border-indigo-400 hover:bg-indigo-50/40">
        <Upload className="size-4 shrink-0" />
        <span className="truncate">{archivo?.name ?? `Elegir ${acepta.replace('.', '').toUpperCase()}…`}</span>
        <input type="file" accept={acepta} className="hidden" onChange={(e) => setArchivo(e.target.files?.[0] ?? null)} />
      </label>
      <Boton variante="primario" disabled={!archivo} cargando={cargando} onClick={() => archivo && onArchivo(archivo)}>
        {texto}
      </Boton>
    </div>
  )
}

export default function Cargar() {
  const { data: personas = [] } = useQuery({ queryKey: ['trabajadores'], queryFn: api.trabajadores })
  const [vista, setVista] = useState<VistaCarga>('liquidaciones')
  const detalle: Record<VistaCarga, string> = {
    liquidaciones: 'Excel, PDF o Buk. Cada carga reemplaza lo vigente del mes y vuelve a abrir los casos con diferencias.',
    trabajador: 'Contrato y anexos de una persona. Cambian la ficha y el contexto que usa el agente para esa liquidación.',
    organizacionales: 'Reglamento, políticas y normativa de la clínica. Son el contexto que la IA necesita para entender cómo opera la organización.',
  }

  return (
    <div className="mx-auto h-full max-w-6xl space-y-5 overflow-y-auto overscroll-contain p-6">
      <div>
        <h1 className="text-[1.65rem] font-bold tracking-tight text-slate-900">Cargar</h1>
        <p className="mt-1 text-sm text-slate-500">{detalle[vista]}</p>
      </div>
      <Pestanas
        valor={vista}
        onCambio={setVista}
        opciones={[
          { id: 'liquidaciones', texto: 'Liquidaciones' },
          { id: 'trabajador', texto: 'De un trabajador' },
          { id: 'organizacionales', texto: 'Organizacionales' },
        ]}
      />
      {vista === 'liquidaciones' && <Liquidaciones personas={personas} />}
      {vista === 'trabajador' && <Contratos personas={personas} />}
      {vista === 'organizacionales' && <Organizacionales />}
    </div>
  )
}

function Liquidaciones({ personas }: { personas: Trabajador[] }) {
  const invalidar = ['liquidaciones', 'bandeja', 'caso', 'borradores', 'historial']
  const excel = useCarga('/cargas/excel', invalidar)
  const pdf = useCarga('/cargas/pdf-liquidacion', invalidar)
  const { data: cargadas, isLoading } = useQuery({ queryKey: ['liquidaciones'], queryFn: api.liquidaciones })
  const nombres = Object.fromEntries(personas.map((p) => [p.worker_id, p.nombre]))
  return (
    <div className="grid gap-5 lg:grid-cols-[380px_minmax(0,1fr)]">
      <div className="space-y-4">
        <Tarjeta titulo={<span className="flex items-center gap-1.5"><FileSpreadsheet className="size-4 text-emerald-600" />Liquidaciones en Excel</span>}
          accion={<a href={api.urlPlantilla()} className="flex items-center gap-1 text-xs font-medium text-indigo-600 hover:underline">
            <Download className="size-3.5" />Plantilla</a>}>
          <SubirArchivo acepta=".xlsx" texto="Cargar" cargando={excel.isPending}
            onArchivo={(archivo) => excel.mutate({ archivo })} />
        </Tarjeta>
        <Tarjeta titulo={<span className="flex items-center gap-1.5"><FileText className="size-4 text-rose-600" />Liquidaciones en PDF</span>}>
          <p className="mb-2 text-xs text-slate-500">PDF con texto. Un bloque «LIQUIDACION DE SUELDO» por trabajador.</p>
          <SubirArchivo acepta=".pdf" texto="Cargar" cargando={pdf.isPending}
            onArchivo={(archivo) => pdf.mutate({ archivo })} />
        </Tarjeta>
        <Buk />
      </div>
      <Tarjeta titulo="Liquidaciones en la base">
        {isLoading || !cargadas ? <Cargando /> : (
          <div className="max-h-80 overflow-y-auto overscroll-contain">
            <table className="w-full text-sm">
              <thead className="sticky top-0 bg-white text-left text-xs text-slate-500">
                <tr><th className="pb-2 font-medium">Trabajador</th><th className="pb-2 font-medium">Mes</th>
                  <th className="pb-2 text-right font-medium">Líquido</th><th className="pb-2 pl-4 font-medium">Origen</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {[...cargadas].sort((a, b) => b.periodo.localeCompare(a.periodo) || a.worker_id.localeCompare(b.worker_id))
                  .map((l) => (
                    <tr key={`${l.worker_id}-${l.periodo}`}>
                      <td className="py-2">{nombres[l.worker_id] ?? l.worker_id}</td>
                      <td className="py-2 text-slate-500">{mes(l.periodo)}</td>
                      <td className="py-2 text-right tabular-nums">{clp(l.liquido_a_pagar)}</td>
                      <td className="py-2 pl-4">
                        <Etiqueta tono={l.origen === 'rectificada' ? 'verde' : 'gris'}>{ORIGEN[l.origen] ?? l.origen}</Etiqueta>
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </Tarjeta>
    </div>
  )
}

function Buk() {
  const cliente = useQueryClient()
  const { data: conectores } = useQuery({ queryKey: ['conectores'], queryFn: api.conectores })
  const modo = conectores?.find((c) => c.nombre === 'Buk')?.modo
  const [periodo, setPeriodo] = useState(hoy().slice(0, 7))
  const sincronizar = useMutation({
    mutationFn: () => api.sincronizarBuk(periodo),
    onSuccess: (r) => {
      toast.success(r.resumen)
      ;['liquidaciones', 'bandeja', 'caso', 'borradores', 'historial', 'trabajadores', 'contratos']
        .forEach((k) => cliente.invalidateQueries({ queryKey: [k] }))
    },
    onError: (e) => toast.error(e.message),
  })
  const r = sincronizar.data
  return (
    <Tarjeta className="ring-sky-200"
      titulo={<span className="flex items-center gap-1.5"><PlugZap className="size-4 text-sky-600" />Buk</span>}
      accion={modo === 'demo' ? <Etiqueta tono="ambar">Demostración</Etiqueta>
        : modo === 'api' ? <Etiqueta tono="verde">Conectado</Etiqueta> : null}>
      <p className="mb-3 text-xs text-slate-500">
        Trae los trabajadores activos y las liquidaciones del mes. Da de alta a quien no esté y actualiza AFP,
        salud, contrato y sueldo base.
        {modo === 'demo' && ' Sin token: responde una instancia de ejemplo con el formato de la API de Buk.'}
      </p>
      <div className="flex items-center gap-2">
        <Entrada type="month" value={periodo} onChange={(e) => setPeriodo(e.target.value)} className="w-40"
          aria-label="Mes a traer de Buk" />
        <Boton variante="primario" className="flex-1" cargando={sincronizar.isPending} disabled={!periodo}
          onClick={() => sincronizar.mutate()}>
          {!sincronizar.isPending && <RefreshCw className="size-4" />}Sincronizar
        </Boton>
      </div>
      {r && (
        <div className="mt-3 space-y-2 rounded-lg border border-transparent bg-slate-50 p-3 text-xs text-slate-600 ring-1 ring-slate-100">
          <p>{r.trabajadores} trabajadores · {r.liquidaciones} liquidaciones de {mes(r.periodo)}</p>
          {r.altas.map((a) => (
            <p key={a.worker_id} className="flex items-center gap-1.5">
              <Etiqueta tono="azul">Alta</Etiqueta>{a.worker_id} · {a.nombre}
            </p>
          ))}
          {r.actualizados.map((a) => (
            <p key={a.worker_id} className="flex flex-wrap items-center gap-1.5">
              <Etiqueta tono="indigo">Ficha</Etiqueta>{a.nombre}:
              {Object.entries(a.cambios).map(([campo, [antes, despues]]) => (
                <span key={campo}>{CAMPOS[campo] ?? campo} {String(antes ?? '—')} → {String(despues ?? '—')}</span>
              ))}
            </p>
          ))}
          {r.casos.length > 0 ? (
            <p className="flex flex-wrap items-center gap-1.5">
              <Etiqueta tono="rojo">Con diferencias</Etiqueta>
              {r.casos.map((id) => (
                <Link key={id} to={`/bandeja/${id}`} className="font-medium text-indigo-600 hover:underline">{id}</Link>
              ))}
            </p>
          ) : r.liquidaciones > 0 && <p><Etiqueta tono="verde">Sin diferencias</Etiqueta></p>}
        </div>
      )}
    </Tarjeta>
  )
}

type FichaForm = {
  afp: string
  tipo_contrato: string
  sueldo_base: string
  bono_monto: string
  bono_meta_atenciones: string
  asignacion_turno: string
}

const FICHA_FORM_VACIA: FichaForm = {
  afp: '', tipo_contrato: '', sueldo_base: '', bono_monto: '', bono_meta_atenciones: '', asignacion_turno: '',
}

const ETIQUETAS_FICHA: Record<keyof FichaForm, string> = {
  afp: 'AFP',
  tipo_contrato: 'Tipo de contrato',
  sueldo_base: 'Sueldo base',
  bono_monto: 'Bono de productividad',
  bono_meta_atenciones: 'Meta de atenciones',
  asignacion_turno: 'Asignación de turno',
}

function formDesdeCambios(cambios: Record<string, string | number>): FichaForm {
  return {
    afp: cambios.afp != null ? String(cambios.afp) : '',
    tipo_contrato: cambios.tipo_contrato != null ? String(cambios.tipo_contrato) : '',
    sueldo_base: cambios.sueldo_base != null ? String(cambios.sueldo_base) : '',
    bono_monto: cambios.bono_monto != null ? String(cambios.bono_monto) : '',
    bono_meta_atenciones: cambios.bono_meta_atenciones != null ? String(cambios.bono_meta_atenciones) : '',
    asignacion_turno: cambios.asignacion_turno != null ? String(cambios.asignacion_turno) : '',
  }
}

function cambiosDe(ficha: FichaForm): string {
  const cambios: Record<string, string | number> = {}
  if (ficha.afp) cambios.afp = ficha.afp
  if (ficha.tipo_contrato) cambios.tipo_contrato = ficha.tipo_contrato
  for (const k of ['sueldo_base', 'bono_monto', 'bono_meta_atenciones', 'asignacion_turno'] as const) {
    if (ficha[k] !== '') cambios[k] = Number(ficha[k])
  }
  return Object.keys(cambios).length ? JSON.stringify(cambios) : ''
}

function evidenciaDe(lectura: LecturaDocumento, campo: keyof FichaForm): PropuestaCampo | null {
  const prop = lectura.propuesta[campo]
  return prop ?? null
}

function fmtVista(valor: string | number | null | undefined): string {
  if (valor == null || valor === '') return '—'
  if (typeof valor === 'number') return clp(valor)
  return String(valor).replace('_', ' ')
}

const hoy = () => new Date().toLocaleDateString('sv-SE', { timeZone: 'America/Santiago' })

function WizardDocumento({
  kind, workerId, onConfirmado,
}: {
  kind: 'contrato' | 'anexo'
  workerId: string
  onConfirmado: () => void
}) {
  const [desde, setDesde] = useState(hoy())
  const [descripcion, setDescripcion] = useState('')
  const [archivo, setArchivo] = useState<File | null>(null)
  const [lectura, setLectura] = useState<LecturaDocumento | null>(null)
  const [ficha, setFicha] = useState<FichaForm>(FICHA_FORM_VACIA)

  const leer = useMutation({
    mutationFn: async () => {
      if (!archivo) throw new Error('Elige un PDF primero.')
      return kind === 'contrato'
        ? api.leerContrato(archivo, workerId, desde)
        : api.leerAnexo(archivo, workerId, desde, descripcion)
    },
    onSuccess: (r) => {
      setLectura(r)
      setFicha(formDesdeCambios(r.cambios_sugeridos))
      toast.success('Lectura lista para revisar')
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const confirmar = useMutation({
    mutationFn: async () => {
      if (!archivo) throw new Error('No hay PDF.')
      const campos: Record<string, string> = {
        worker_id: workerId,
        vigente_desde: desde,
        cambios: cambiosDe(ficha),
      }
      if (kind === 'anexo') campos.descripcion = descripcion
      return api.cargarArchivo(kind === 'contrato' ? '/cargas/pdf' : '/cargas/anexo', archivo, campos)
    },
    onSuccess: (r) => {
      toast.success(r.resumen)
      setArchivo(null)
      setLectura(null)
      setFicha(FICHA_FORM_VACIA)
      setDescripcion('')
      onConfirmado()
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const descartar = () => {
    setLectura(null)
    setFicha(FICHA_FORM_VACIA)
  }

  const poner = (k: keyof FichaForm, v: string) => setFicha({ ...ficha, [k]: v })

  return (
    <Tarjeta titulo={kind === 'contrato' ? 'Reemplazar contrato' : 'Agregar anexo'}>
      <div className="space-y-3">
        <p className="text-xs text-slate-500">
          {kind === 'contrato'
            ? 'La IA lee el PDF y propone la ficha. Tú confirmas antes de guardar en el corpus.'
            : 'Se suma al contrato. La IA propone los cambios; tú confirmas antes de guardar.'}
        </p>
        <div className={`grid gap-3 ${kind === 'anexo' ? 'grid-cols-2' : ''}`}>
          <Rotulo texto="Vigente desde">
            <Entrada type="date" value={desde} onChange={(e) => setDesde(e.target.value)} />
          </Rotulo>
          {kind === 'anexo' && (
            <Rotulo texto="De qué trata">
              <Entrada value={descripcion} onChange={(e) => setDescripcion(e.target.value)}
                placeholder="Ej.: cambio de AFP" />
            </Rotulo>
          )}
        </div>
        <div className="flex items-center gap-2">
          <label className="flex min-w-0 flex-1 cursor-pointer items-center gap-2 rounded-lg border border-dashed border-slate-300
            px-3 py-2 text-sm text-slate-500 hover:border-indigo-400 hover:bg-indigo-50/40">
            <Upload className="size-4 shrink-0" />
            <span className="truncate">{archivo?.name ?? 'Elegir PDF…'}</span>
            <input type="file" accept=".pdf" className="hidden"
              onChange={(e) => { setArchivo(e.target.files?.[0] ?? null); setLectura(null) }} />
          </label>
          <Boton variante="primario" disabled={!archivo} cargando={leer.isPending} onClick={() => leer.mutate()}>
            <span className="inline-flex items-center gap-1.5">
              <Sparkles className="size-3.5" />
              Leer con IA
            </span>
          </Boton>
        </div>

        {lectura && (
          <div className="space-y-3 rounded-2xl border border-indigo-100 bg-indigo-50/40 p-3">
            <p className="text-sm text-indigo-950">{lectura.propuesta.resumen}</p>
            {lectura.propuesta.campos_no_mapeados.length > 0 && (
              <ul className="list-disc space-y-0.5 pl-4 text-xs text-slate-600">
                {lectura.propuesta.campos_no_mapeados.map((c) => <li key={c}>{c}</li>)}
              </ul>
            )}
            <div className="grid gap-3 sm:grid-cols-2">
              <Rotulo texto="AFP">
                <Selector value={ficha.afp} onChange={(e) => poner('afp', e.target.value)}>
                  <option value="">sin cambio</option>
                  {AFP.map((a) => <option key={a}>{a}</option>)}
                </Selector>
                <Evidencia prop={evidenciaDe(lectura, 'afp')} />
              </Rotulo>
              <Rotulo texto="Tipo de contrato">
                <Selector value={ficha.tipo_contrato} onChange={(e) => poner('tipo_contrato', e.target.value)}>
                  <option value="">sin cambio</option>
                  <option value="indefinido">Indefinido</option>
                  <option value="plazo_fijo">Plazo fijo</option>
                </Selector>
                <Evidencia prop={evidenciaDe(lectura, 'tipo_contrato')} />
              </Rotulo>
              {(['sueldo_base', 'bono_monto', 'bono_meta_atenciones', 'asignacion_turno'] as const).map((k) => (
                <Rotulo key={k} texto={ETIQUETAS_FICHA[k]}>
                  <Entrada type="number" min={0} value={ficha[k]} placeholder="sin cambio"
                    onChange={(e) => poner(k, e.target.value)} />
                  <Evidencia prop={evidenciaDe(lectura, k)} />
                </Rotulo>
              ))}
            </div>
            <DiffFicha actual={lectura.ficha_actual} propuesta={lectura.ficha_propuesta} editada={ficha} />
            <PreviewDescuentosBlock preview={lectura.preview_descuentos} />
            <details className="rounded-lg bg-white/70 px-3 py-2 text-xs text-slate-600 ring-1 ring-slate-100">
              <summary className="cursor-pointer font-medium">Texto extraído del PDF</summary>
              <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap font-sans leading-relaxed">
                {lectura.texto}
              </pre>
            </details>
            <div className="flex flex-wrap justify-end gap-2">
              <Boton variante="secundario" onClick={descartar}>Descartar</Boton>
              <Boton variante="primario" cargando={confirmar.isPending} onClick={() => confirmar.mutate()}>
                Confirmar y cargar
              </Boton>
            </div>
          </div>
        )}
      </div>
    </Tarjeta>
  )
}

function Evidencia({ prop }: { prop: PropuestaCampo | null }) {
  if (!prop?.evidencia) return null
  return (
    <p className="mt-1 text-[11px] leading-snug text-slate-500">
      <span className="font-medium text-slate-600">{prop.confianza}</span>
      {' · '}
      “{prop.evidencia}”
    </p>
  )
}

function DiffFicha({
  actual, propuesta, editada,
}: {
  actual: VistaFicha
  propuesta: VistaFicha
  editada: FichaForm
}) {
  const filas = (Object.keys(ETIQUETAS_FICHA) as (keyof FichaForm)[]).filter((k) => {
    const edit = editada[k]
    const antes = actual[k as keyof VistaFicha]
    const sugerido = propuesta[k as keyof VistaFicha]
    return edit !== '' || (sugerido != null && String(sugerido) !== String(antes ?? ''))
  })
  if (!filas.length) {
    return <p className="text-xs text-slate-500">Sin cambios tipados respecto de la ficha actual.</p>
  }
  return (
    <div className="overflow-hidden rounded-xl bg-white text-xs ring-1 ring-slate-100">
      <table className="w-full">
        <thead className="bg-slate-50 text-left text-slate-500">
          <tr>
            <th className="px-3 py-2 font-medium">Campo</th>
            <th className="px-3 py-2 font-medium">Antes</th>
            <th className="px-3 py-2 font-medium">Después</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-100">
          {filas.map((k) => {
            const despues = editada[k] !== '' ? editada[k] : String(propuesta[k as keyof VistaFicha] ?? '')
            return (
              <tr key={k}>
                <td className="px-3 py-2 font-medium text-slate-700">{ETIQUETAS_FICHA[k]}</td>
                <td className="px-3 py-2 text-slate-500">{fmtVista(actual[k as keyof VistaFicha])}</td>
                <td className="px-3 py-2 text-indigo-800">
                  {k === 'sueldo_base' || k === 'bono_monto' || k === 'asignacion_turno'
                    ? (despues ? clp(Number(despues)) : '—')
                    : (despues || '—').replace('_', ' ')}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function PreviewDescuentosBlock({
  preview,
}: {
  preview: LecturaDocumento['preview_descuentos']
}) {
  const a = preview.actual
  const p = preview.propuesta
  if (!a.lineas.length && !p.lineas.length) return null
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      {([
        ['Con ficha actual', a],
        ['Con ficha propuesta', p],
      ] as const).map(([titulo, bloque]) => (
        <div key={titulo} className="rounded-xl bg-white px-3 py-2 text-xs ring-1 ring-slate-100">
          <p className="mb-1.5 font-medium text-slate-700">{titulo}</p>
          <p className="text-slate-500">Imponible est. {clp(bloque.imponible)}</p>
          <ul className="mt-1 space-y-0.5 text-slate-600">
            {bloque.lineas.map((l) => (
              <li key={l.codigo} className="flex justify-between gap-2">
                <span className="truncate">{l.concepto}</span>
                <span className="tabular-nums">{clp(l.monto)}</span>
              </li>
            ))}
          </ul>
          <p className="mt-1.5 flex justify-between border-t border-slate-100 pt-1.5 font-medium">
            <span>Total</span>
            <span className="tabular-nums">{clp(bloque.total)}</span>
          </p>
        </div>
      ))}
    </div>
  )
}

function etiquetaDoc(d: DocumentoContrato) {
  if (d.tipo === 'contrato') return 'Contrato'
  return d.descripcion?.trim() || 'Anexo'
}

function Contratos({ personas }: { personas: Trabajador[] }) {
  const cliente = useQueryClient()
  const [worker, setWorker] = useState('')
  const elegido = worker || personas[0]?.worker_id || ''
  const [docActivo, setDocActivo] = useState('')

  const { data: vigentes } = useQuery({ queryKey: ['contratos'], queryFn: api.contratos })
  const { data: docs, isLoading: cargandoDocs } = useQuery({
    queryKey: ['documentos-contrato', elegido],
    queryFn: () => api.documentosContrato(elegido),
    enabled: Boolean(elegido),
  })

  useEffect(() => {
    setDocActivo('')
  }, [elegido])

  useEffect(() => {
    if (!docs?.length) return
    if (!docActivo || !docs.some((d) => d.documento === docActivo)) {
      setDocActivo(docs[0].documento)
    }
  }, [docs, docActivo])

  const invalidarTrasCarga = () => {
    ;['contratos', 'documentos-contrato', 'bandeja', 'caso', 'borradores'].forEach((k) => {
      cliente.invalidateQueries({ queryKey: [k] })
    })
  }

  const ficha = vigentes?.find((c) => c.worker_id === elegido)
  const actual = docs?.find((d) => d.documento === docActivo) ?? docs?.[0]

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <label className="flex items-center gap-2.5 rounded-xl bg-orange-500 px-4 py-2 text-white shadow-sm">
          <UserRound className="size-5 shrink-0" />
          <span className="text-sm font-medium">Trabajador</span>
          <select
            value={elegido}
            onChange={(e) => setWorker(e.target.value)}
            aria-label="Trabajador del contrato o anexo"
            className="min-w-72 bg-transparent text-lg font-semibold focus:outline-none"
          >
            {personas.map((p) => <option key={p.worker_id} value={p.worker_id} className="text-slate-900">
              {p.worker_id} · {p.nombre}
            </option>)}
          </select>
        </label>
        {ficha && (
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
            <Etiqueta tono="gris">{ficha.ficha.afp}</Etiqueta>
            <Etiqueta tono="gris">{ficha.ficha.tipo_contrato.replace('_', ' ')}</Etiqueta>
            <Etiqueta tono="indigo">{clp(ficha.ficha.sueldo_base)}</Etiqueta>
            <span className="text-slate-400">desde {ficha.vigente_desde ?? '—'}</span>
          </div>
        )}
      </div>

      <Tarjeta titulo="Contrato y anexos">
        {cargandoDocs || !docs ? <Cargando /> : docs.length === 0 ? (
          <p className="text-sm text-slate-500">Este trabajador aún no tiene contrato ni anexos en el corpus.</p>
        ) : (
          <div className="grid gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
            <ul className="space-y-1">
              {docs.map((d) => {
                const activo = d.documento === (actual?.documento ?? '')
                return (
                  <li key={d.documento}>
                    <button
                      type="button"
                      onClick={() => setDocActivo(d.documento)}
                      className={`w-full rounded-xl px-3 py-2.5 text-left transition ${
                        activo ? 'bg-indigo-50 text-indigo-950 ring-1 ring-indigo-200' : 'hover:bg-slate-50'
                      }`}
                    >
                      <p className="text-sm font-medium">{etiquetaDoc(d)}</p>
                      <p className="text-xs text-slate-500">
                        {d.tipo === 'contrato' ? 'Contrato' : 'Anexo'}
                        {d.vigente_desde ? ` · ${d.vigente_desde}` : ''}
                      </p>
                    </button>
                  </li>
                )
              })}
            </ul>
            {actual && (
              <div className="min-w-0 rounded-2xl border border-slate-100 bg-slate-50/70 p-4">
                <div className="mb-3 flex flex-wrap items-start justify-between gap-2">
                  <div>
                    <p className="font-medium text-slate-900">{etiquetaDoc(actual)}</p>
                    <p className="text-xs text-slate-500">
                      {actual.documento}
                      {actual.cargado ? ` · cargado ${hora(actual.cargado)}` : ''}
                      {` · ${actual.origen === 'cargado' ? 'cargado' : actual.origen === 'buk' ? 'Buk' : 'inicial'}`}
                    </p>
                    {Object.keys(actual.cambios).length > 0 && (
                      <p className="mt-1 text-xs text-slate-500">
                        Cambia: {Object.keys(actual.cambios).map((k) => CAMPOS[k] ?? k).join(', ')}
                      </p>
                    )}
                  </div>
                  {actual.tipo === 'contrato' && (
                    <a
                      href={api.urlContratoPdf(elegido)}
                      target="_blank"
                      rel="noreferrer"
                      className="inline-flex items-center gap-1.5 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
                    >
                      <ExternalLink className="size-3.5" />
                      Ver PDF
                    </a>
                  )}
                </div>
                <pre className="max-h-[28rem] overflow-auto whitespace-pre-wrap font-sans text-sm leading-relaxed text-slate-800">
                  {actual.contenido || '(sin contenido)'}
                </pre>
              </div>
            )}
          </div>
        )}
      </Tarjeta>

      <div className="grid gap-5 lg:grid-cols-2">
        <WizardDocumento key={`c-${elegido}`} kind="contrato" workerId={elegido} onConfirmado={invalidarTrasCarga} />
        <WizardDocumento key={`a-${elegido}`} kind="anexo" workerId={elegido} onConfirmado={invalidarTrasCarga} />
      </div>
    </div>
  )
}

const TIPOS_COMPARTIDOS = [
  { id: 'reglamento', texto: 'Reglamento' },
  { id: 'politica', texto: 'Política' },
  { id: 'normativa', texto: 'Normativa' },
  { id: 'otro', texto: 'Otro' },
] as const

function Organizacionales() {
  const cliente = useQueryClient()
  const [tipo, setTipo] = useState<string>('reglamento')
  const [descripcion, setDescripcion] = useState('')
  const { data: docs, isLoading } = useQuery({
    queryKey: ['documentos-compartidos'], queryFn: api.documentosCompartidos,
  })
  const subir = useMutation({
    mutationFn: (archivo: File) => api.cargarArchivo('/cargas/documento-compartido', archivo, {
      doc_type: tipo, descripcion,
    }),
    onSuccess: (r) => {
      toast.success(r.resumen)
      cliente.invalidateQueries({ queryKey: ['documentos-compartidos'] })
    },
    onError: (e: Error) => toast.error(e.message),
  })

  return (
    <div className="space-y-5">
      <div className="rounded-2xl border border-indigo-100 bg-indigo-50/60 px-4 py-3 text-sm text-indigo-950">
        Estos documentos no pertenecen a un trabajador: son la base organizacional.
        Sin ellos, la IA no conoce reglamento, políticas de bono ni normativa interna al responder.
      </div>
      <div className="grid gap-5 lg:grid-cols-[380px_minmax(0,1fr)]">
        <Tarjeta titulo="Subir documento organizacional">
          <div className="space-y-3">
            <Rotulo texto="Tipo">
              <Selector value={tipo} onChange={(e) => setTipo(e.target.value)}>
                {TIPOS_COMPARTIDOS.map((t) => <option key={t.id} value={t.id}>{t.texto}</option>)}
              </Selector>
            </Rotulo>
            <Rotulo texto="Descripción">
              <Entrada value={descripcion} onChange={(e) => setDescripcion(e.target.value)}
                placeholder="Ej.: reglamento interno 2026" />
            </Rotulo>
            <SubirArchivo acepta=".pdf,.md" texto="Cargar PDF o Markdown" cargando={subir.isPending}
              onArchivo={(archivo) => subir.mutate(archivo)} />
          </div>
        </Tarjeta>
        <Tarjeta titulo="En el corpus del agente">
          {isLoading || !docs ? <Cargando /> : docs.length === 0 ? (
            <p className="text-sm text-slate-500">Todavía no hay documentos organizacionales.</p>
          ) : (
            <ul className="divide-y divide-slate-100 text-sm">
              {docs.map((d) => (
                <li key={d.documento} className="flex items-start justify-between gap-3 py-2.5">
                  <div className="min-w-0">
                    <p className="truncate font-medium text-slate-800">{d.documento}</p>
                    <p className="text-xs text-slate-500">
                      {d.tipo}{d.descripcion ? ` · ${d.descripcion}` : ''}
                      {d.cargado ? ` · ${hora(d.cargado)}` : ''}
                    </p>
                  </div>
                  <Etiqueta tono={d.origen === 'cargado' ? 'indigo' : 'gris'}>
                    {d.origen === 'cargado' ? 'Cargado' : 'Inicial'}
                  </Etiqueta>
                </li>
              ))}
            </ul>
          )}
        </Tarjeta>
      </div>
    </div>
  )
}

