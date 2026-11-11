import { useQuery } from '@tanstack/react-query'
import { Cable, FileSpreadsheet, FileText, PlugZap } from 'lucide-react'

import { Cargando, cn, Etiqueta } from '../components/ui'
import { api } from '../lib/api'

const ICONOS: Record<string, typeof Cable> = { Excel: FileSpreadsheet, 'PDF liquidación': FileText, PDF: FileText }

export default function Conectores() {
  const { data: lista, isLoading } = useQuery({ queryKey: ['conectores'], queryFn: api.conectores })
  if (isLoading || !lista) return <Cargando />
  return (
    <div className="mx-auto h-full max-w-4xl space-y-5 overflow-y-auto overscroll-contain p-6">
      <div>
        <h1 className="text-[1.65rem] font-bold tracking-tight text-slate-900">Conectores</h1>
        <p className="text-sm text-slate-500">Por dónde entran las liquidaciones y los contratos al sistema.</p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {lista.map((c) => {
          const Icono = ICONOS[c.nombre] ?? PlugZap
          return (
            <div key={c.nombre} className={cn('flex gap-3 rounded-2xl border border-slate-100 bg-white p-4 shadow-[0_10px_30px_-18px_rgba(40,60,120,0.45)]',
              !c.disponible && 'opacity-70')}>
              <span className={cn('grid size-10 shrink-0 place-items-center rounded-lg',
                c.disponible ? 'bg-indigo-50 text-indigo-600' : 'bg-slate-100 text-slate-400')}>
                <Icono className="size-5" />
              </span>
              <div className="space-y-1">
                <div className="flex items-center gap-2">
                  <p className="font-medium">{c.nombre}</p>
                  <Etiqueta tono={c.disponible ? 'verde' : 'gris'}>{c.disponible ? 'Disponible' : 'Próximamente'}</Etiqueta>
                  {c.modo === 'demo' && <Etiqueta tono="ambar">Demostración</Etiqueta>}
                </div>
                <p className="text-sm text-slate-500">{c.detalle}</p>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
