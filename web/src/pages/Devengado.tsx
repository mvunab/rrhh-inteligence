import { useQuery } from '@tanstack/react-query'
import { ArrowRight, Bot, MessageSquare } from 'lucide-react'
import { Link } from 'react-router-dom'

import { Cargando, cn, Vacio } from '../components/ui'
import { api, type Borrador, type ItemBandeja } from '../lib/api'
import { caminoDe, relato, type Camino } from '../lib/camino'
import { delta, mes } from '../lib/formato'

const PASOS: Record<Camino, string[]> = {
  agente: [
    'Se carga la liquidación, por Excel, PDF o desde Buk.',
    'El agente la compara con el contrato vigente y la ley del mes.',
    'Deja el monto a favor, listo para que RR.HH. lo revise y lo emita.',
  ],
  conversacion: [
    'El trabajador pregunta desde su chat.',
    'El agente responde con su liquidación y, si no cuadra, abre el caso.',
    'RR.HH. lo ve en la bandeja, con la conversación al lado, y emite.',
  ],
}

const ESTILO: Record<Camino, { kicker: string; titulo: string; icono: typeof Bot; panel: string; numero: string; paso: string }> = {
  agente: {
    kicker: 'Sin que nadie pregunte',
    titulo: 'Lo devenga el agente',
    icono: Bot,
    panel: 'bg-violet-50 ring-violet-200',
    numero: 'text-violet-700',
    paso: 'bg-violet-600',
  },
  conversacion: {
    kicker: 'Porque el trabajador escribió',
    titulo: 'Lo devenga la conversación',
    icono: MessageSquare,
    panel: 'bg-orange-50 ring-orange-200',
    numero: 'text-orange-700',
    paso: 'bg-orange-500',
  },
}

function aFavor(item: ItemBandeja, borradores: Borrador[]): number | null {
  const borrador = borradores.find((b) => b.id === `B-${item.worker_id}-${item.periodo}`)
  if (!borrador) return item.tipo === 'diferencia' ? item.diferencia_total : null
  return borrador.propuesta.liquido_a_pagar - borrador.original.liquido_a_pagar
}

function preguntaDe(item: ItemBandeja): string | null {
  const mensajes = item.solicitudes.flatMap((s) => s.mensajes.map((m) => ({ cuando: m.creado, texto: m.texto })))
  mensajes.sort((a, b) => a.cuando.localeCompare(b.cuando))
  return mensajes[0]?.texto ?? item.solicitudes[0]?.pregunta ?? null
}

export default function Devengado() {
  const bandeja = useQuery({ queryKey: ['bandeja'], queryFn: api.bandeja })
  const borradores = useQuery({ queryKey: ['borradores'], queryFn: api.borradores })
  if (bandeja.isLoading || borradores.isLoading || !bandeja.data || !borradores.data) return <Cargando />

  const grupos: Record<Camino, ItemBandeja[]> = { agente: [], conversacion: [] }
  for (const item of bandeja.data) grupos[caminoDe(item)].push(item)
  const suma = (camino: Camino) => grupos[camino].reduce((s, item) => s + (aFavor(item, borradores.data) ?? 0), 0)

  return (
    <div className="h-full overflow-y-auto overscroll-contain">
      <div className="mx-auto max-w-6xl space-y-8 p-6">
        <header className="max-w-3xl">
          <h1 className="text-[1.65rem] font-bold tracking-tight text-slate-900">Lo devengado</h1>
          <p className="mt-1 text-sm leading-relaxed text-slate-600">
            Dos caminos dejan plata a favor del trabajador. En los dos el agente calcula; cambia quién lo pone en marcha.
            El número es el líquido que recibiría de más. Los haberes, lo devengado en la liquidación, siguen iguales:
            lo que estaba mal era el descuento.
          </p>
        </header>

        <div className="grid gap-6 lg:grid-cols-2">
          {(['agente', 'conversacion'] as const).map((camino) => (
            <Columna key={camino} camino={camino} items={grupos[camino]} total={suma(camino)} borradores={borradores.data} />
          ))}
        </div>
      </div>
    </div>
  )
}

function Columna({ camino, items, total, borradores }: {
  camino: Camino; items: ItemBandeja[]; total: number; borradores: Borrador[] }) {
  const estilo = ESTILO[camino]
  const Icono = estilo.icono
  return (
    <section className={cn('flex flex-col gap-5 rounded-2xl border border-transparent p-5 ring-1', estilo.panel)}>
      <div>
        <p className="flex items-center gap-1.5 text-xs font-semibold tracking-wide uppercase">
          <Icono className={cn('size-4', estilo.numero)} />
          <span className={estilo.numero}>{estilo.kicker}</span>
        </p>
        <h2 className="mt-1 text-lg font-semibold text-slate-900">{estilo.titulo}</h2>
        <p className={cn('mt-2 text-3xl font-semibold tabular-nums', total > 0 ? estilo.numero : 'text-slate-400')}>
          {delta(total)}
        </p>
        <p className="text-xs text-slate-500">A favor del trabajador, sumando los casos de abajo.</p>
      </div>

      <ol className="space-y-2.5">
        {PASOS[camino].map((paso, i) => (
          <li key={paso} className="flex gap-2.5 text-sm text-slate-700">
            <span className={cn('grid size-5 shrink-0 place-items-center rounded-full text-[11px] font-semibold text-white', estilo.paso)}>
              {i + 1}
            </span>
            {paso}
          </li>
        ))}
      </ol>

      <div className="space-y-3">
        {items.length === 0 && (
          <Vacio titulo={camino === 'agente' ? 'El agente no ha marcado ninguna liquidación' : 'Nadie ha escrito todavía'}>
            {camino === 'agente'
              ? 'Aparece al cargar una liquidación que no cuadra con el contrato.'
              : 'Aparece cuando un trabajador pregunta por la suya y el agente encuentra algo.'}
          </Vacio>
        )}
        {items.map((item) => (
          <Caso key={item.id} item={item} camino={camino} monto={aFavor(item, borradores)} />
        ))}
      </div>
    </section>
  )
}

function Caso({ item, camino, monto }: { item: ItemBandeja; camino: Camino; monto: number | null }) {
  const pregunta = camino === 'conversacion' ? preguntaDe(item) : null
  const vista = camino === 'conversacion' ? 'conversacion' : 'propuesta'
  return (
    <article className="rounded-2xl border border-slate-100 bg-white p-4 shadow-[0_10px_30px_-18px_rgba(40,60,120,0.45)]">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="font-medium text-slate-900">{item.nombre}</p>
          <p className="text-xs text-slate-500">{item.area} · {mes(item.periodo)}</p>
        </div>
        <p className={cn('text-lg font-semibold tabular-nums', (monto ?? 0) > 0 ? 'text-emerald-700' : 'text-slate-500')}>
          {monto == null ? '—' : delta(monto)}
        </p>
      </div>
      <p className="mt-3 text-sm leading-relaxed text-slate-600">{relato(item)}</p>
      {pregunta && (
        <p className="mt-3 rounded-lg border border-transparent bg-slate-50 px-3 py-2 text-sm text-slate-700 ring-1 ring-slate-100">
          “{pregunta}”
        </p>
      )}
      <Link
        to={`/bandeja/${item.id}?vista=${vista}`}
        className="mt-3 inline-flex items-center gap-1 text-sm font-medium text-indigo-700 hover:underline"
      >
        {camino === 'conversacion' ? 'Ver la conversación' : 'Ver la liquidación corregida'}
        <ArrowRight className="size-4" />
      </Link>
    </article>
  )
}
