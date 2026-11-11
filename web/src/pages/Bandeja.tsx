import { useQuery } from '@tanstack/react-query'
import { Inbox, Search } from 'lucide-react'
import { type ReactNode, useEffect, useMemo, useState } from 'react'
import { Group, Panel, Separator } from 'react-resizable-panels'
import { useNavigate, useParams, useSearchParams } from 'react-router-dom'

import { Cargando, cn, Pestanas, Segmentos, Vacio } from '../components/ui'
import { api, type ItemBandeja } from '../lib/api'
import { relatoRepeticion } from '../lib/camino'
import { clp, mes, titulo } from '../lib/formato'
import Conversacion from './bandeja/Conversacion'
import Diferencia from './bandeja/Diferencia'
import Propuesta from './bandeja/Propuesta'
import Trazabilidad from './bandeja/Trazabilidad'

export const TIPO = { diferencia: 'Diferencia de cálculo', revision: 'Revisión humana' } as const

type Filtro = 'pendientes' | 'todas'

export default function Bandeja() {
  const { itemId } = useParams()
  const navegar = useNavigate()
  const { data: items, isLoading } = useQuery({ queryKey: ['bandeja'], queryFn: api.bandeja })
  const [filtro, setFiltro] = useState<Filtro>('pendientes')
  const [tipo, setTipo] = useState<'todos' | 'diferencia' | 'revision'>('todos')
  const [busqueda, setBusqueda] = useState('')

  const visibles = useMemo(() => (items ?? []).filter((i) =>
    (filtro === 'todas' || i.estado === 'pendiente')
    && (tipo === 'todos' || i.tipo === tipo)
    && `${i.nombre} ${i.area} ${i.worker_id}`.toLowerCase().includes(busqueda.toLowerCase()),
  ), [items, filtro, tipo, busqueda])

  const elegido = items?.find((i) => i.id === itemId)
  useEffect(() => {
    if (!itemId && visibles.length) navegar(`/bandeja/${visibles[0].id}`, { replace: true })
  }, [itemId, visibles, navegar])

  return (
    <Group orientation="horizontal" className="h-full">
      <Panel defaultSize="34" minSize="24" maxSize="50" className="flex flex-col rounded-2xl bg-[#f6f8fd]">
        <div className="space-y-2.5 p-3">
          <div className="flex items-center justify-between">
            <Segmentos<Filtro>
              valor={filtro}
              onCambio={setFiltro}
              opciones={[{ id: 'pendientes', texto: 'Pendientes' }, { id: 'todas', texto: 'Todas' }]}
            />
            <select
              value={tipo}
              onChange={(e) => setTipo(e.target.value as typeof tipo)}
              className="rounded-md bg-transparent py-1 text-xs text-slate-600 focus:outline-none"
            >
              <option value="todos">Todos los tipos</option>
              <option value="diferencia">{TIPO.diferencia}</option>
              <option value="revision">{TIPO.revision}</option>
            </select>
          </div>
          <div className="flex items-center gap-2 rounded-xl bg-white px-3 py-2 shadow-sm ring-1 ring-slate-100">
            <Search className="size-4 text-slate-400" />
            <input
              value={busqueda}
              onChange={(e) => setBusqueda(e.target.value)}
              placeholder="Buscar trabajador o área"
              className="w-full bg-transparent text-sm placeholder:text-slate-400 focus:outline-none"
            />
          </div>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
          {isLoading && <Cargando />}
          {!isLoading && !visibles.length && (
            <Vacio icono={<Inbox className="size-10" />} titulo="Nada por revisar">
              Aparece aquí cuando el motor encuentra una diferencia al cargar una liquidación o cuando un
              trabajador pide que una persona revise la suya.
            </Vacio>
          )}
          <ul className="space-y-0.5 px-2 pb-2">
            {visibles.map((i) => (
              <Fila key={i.id} item={i} activo={i.id === itemId} onClick={() => navegar(`/bandeja/${i.id}`)} />
            ))}
          </ul>
        </div>
        <p className="px-4 py-2 text-xs text-slate-400">
          Una fila por liquidación. {items?.length ?? 0} en revisión.
        </p>
      </Panel>
      <Separator className="w-1 bg-transparent transition hover:bg-indigo-200 data-[separator=active]:bg-indigo-300" />
      <Panel minSize="40" className="min-w-0">
        {elegido ? <Detalle key={elegido.id} item={elegido}
          miembros={(items ?? []).filter((i) => elegido.grupo && i.grupo?.id === elegido.grupo.id)
            .sort((a, b) => (a.periodo ?? '').localeCompare(b.periodo ?? ''))} />
          : <Vacio icono={<Inbox className="size-10" />} titulo="Elige una liquidación de la lista" />}
      </Panel>
    </Group>
  )
}

function Fila({ item, activo, onClick }: { item: ItemBandeja; activo: boolean; onClick: () => void }) {
  const pendientesTrabajador = item.solicitudes.filter((s) => s.estado === 'pendiente').length
  return (
    <li>
      <button
        onClick={onClick}
        className={cn('w-full rounded-2xl border border-transparent px-3 py-3 text-left transition-colors duration-150',
          activo ? 'bg-white shadow-sm ring-1 ring-indigo-100' : 'hover:bg-white/70')}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <p className="flex items-center gap-1.5 truncate text-sm font-medium text-slate-900">
              {item.estado === 'pendiente' && <span className="size-2 shrink-0 rounded-full bg-amber-500" />}
              {item.nombre}
            </p>
            <p className="truncate text-xs text-slate-500">{item.area} · {mes(item.periodo)}</p>
          </div>
          {item.tipo === 'diferencia' && (
            <span className="shrink-0 text-sm font-semibold tabular-nums text-rose-600">{clp(item.diferencia_total)}</span>
          )}
        </div>
        {(pendientesTrabajador > 0 || item.decision) && (
          <p className="mt-1 truncate text-xs text-slate-500">
            {pendientesTrabajador > 0 && (
              <span className="font-medium text-indigo-700">{pendientesTrabajador} sin responder</span>
            )}
            {pendientesTrabajador > 0 && item.decision && ' · '}
            {item.decision && titulo(item.decision)}
          </p>
        )}
      </button>
    </li>
  )
}

type Vista = 'conversacion' | 'diferencia' | 'propuesta' | 'trazabilidad'

function Detalle({ item, miembros }: { item: ItemBandeja; miembros: ItemBandeja[] }) {
  const navegar = useNavigate()
  const grupo = miembros.length > 1 ? item.grupo : null
  const conCaso = !!item.caso_id && (item.tipo === 'diferencia' || !!item.decision)
  const sinResponder = item.solicitudes.filter((s) => s.estado === 'pendiente').length
  const [parametros, setParametros] = useSearchParams()

  const opciones: { id: Vista; texto: ReactNode; aviso?: ReactNode }[] = []
  if (item.solicitudes.length || !conCaso) {
    opciones.push({
      id: 'conversacion',
      texto: 'Conversación',
      aviso: sinResponder ? <span className="rounded-full bg-rose-500 px-1.5 text-[11px] text-white">{sinResponder}</span> : undefined,
    })
  }
  if (conCaso) {
    opciones.push(
      { id: 'diferencia', texto: 'Diferencia' },
      { id: 'propuesta', texto: 'Liquidación corregida' },
      { id: 'trazabilidad', texto: 'Trazabilidad' },
    )
  }
  const pedida = parametros.get('vista') as Vista | null
  const vista: Vista = opciones.some((o) => o.id === pedida) ? pedida!
    : sinResponder || !conCaso ? 'conversacion' : 'diferencia'
  const juntos = !!grupo && parametros.get('juntos') === '1'
  const setVista = (v: Vista) => setParametros(juntos ? { vista: v, juntos: '1' } : { vista: v }, { replace: true })

  return (
    <div className="flex h-full flex-col">
      <header className="shrink-0 px-6 pt-1">
        <div className="flex items-baseline justify-between gap-4">
          <div className="min-w-0">
            <h1 className="truncate text-[1.65rem] font-bold tracking-tight text-slate-900">{item.nombre}</h1>
            <p className="text-sm text-slate-500">{mes(item.periodo)} · {item.area}</p>
          </div>
          {item.tipo === 'diferencia' && (
            <p className="shrink-0 text-2xl font-bold tracking-tight tabular-nums text-rose-600">{clp(item.diferencia_total)}</p>
          )}
        </div>
        {grupo && !juntos && (
          <p className="mt-2 text-sm text-slate-600">
            {relatoRepeticion(miembros)}{' '}
            <button onClick={() => setParametros({ vista, juntos: '1' }, { replace: true })}
              className="font-medium text-indigo-700 hover:underline">
              Verlos juntos
            </button>
          </p>
        )}
        {juntos && (
          <div className="mt-3 flex">
            <div className="flex rounded-[calc(0.375rem+0.125rem+1px)] border border-transparent bg-slate-100 p-0.5" role="tablist" aria-label="Mes">
              {miembros.map((m) => (
                <button key={m.id} role="tab" aria-selected={m.id === item.id}
                  onClick={() => navegar(`/bandeja/${m.id}?vista=${vista}&juntos=1`)}
                  className={cn('rounded-md px-2.5 py-1 text-xs font-medium capitalize transition-colors duration-150',
                    m.id === item.id ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-800')}>
                  {mes(m.periodo)}
                </button>
              ))}
            </div>
          </div>
        )}
        <div className="mt-3">
          <Pestanas valor={vista} onCambio={setVista} opciones={opciones} />
        </div>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
        <div className="relative mx-auto max-w-5xl p-6">
          {vista === 'conversacion' && <Conversacion item={item} />}
          {vista === 'diferencia' && item.caso_id &&
            <Diferencia casoId={item.caso_id} onCorregir={() => setVista('propuesta')}
              grupo={juntos ? miembros : undefined} />}
          {vista === 'propuesta' && <Propuesta item={item} grupo={juntos ? miembros : undefined} />}
          {vista === 'trazabilidad' && <Trazabilidad item={item} />}
        </div>
      </div>
    </div>
  )
}
