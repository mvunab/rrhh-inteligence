import { useQuery } from '@tanstack/react-query'

import { Cargando, Cifra, Tarjeta } from '../components/ui'
import { api } from '../lib/api'

export default function Sectores() {
  const { data: filas, isLoading } = useQuery({ queryKey: ['estadisticas'], queryFn: api.estadisticas })
  if (isLoading || !filas) return <Cargando />
  const total = (k: 'trabajadores' | 'solicitudes' | 'diferencias' | 'revisiones' | 'pendientes') =>
    filas.reduce((s, f) => s + f[k], 0)
  const maximo = Math.max(1, ...filas.map((f) => f.solicitudes))

  return (
    <div className="mx-auto h-full max-w-5xl space-y-5 overflow-y-auto overscroll-contain p-6">
      <div>
        <h1 className="text-[1.65rem] font-bold tracking-tight text-slate-900">Solicitudes por sector</h1>
        <p className="text-sm text-slate-500">Dónde se concentran las consultas que llegan a RR.HH.</p>
      </div>
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        {([['Trabajadores', 'trabajadores'], ['Solicitudes', 'solicitudes'], ['Diferencias de cálculo', 'diferencias'],
          ['Pendientes', 'pendientes']] as const).map(([etiqueta, k]) => (
          <Tarjeta key={k}><Cifra etiqueta={etiqueta} valor={total(k)} /></Tarjeta>
        ))}
      </div>
      <Tarjeta titulo="Por área">
        <table className="w-full text-sm">
          <thead className="text-left text-xs text-slate-500">
            <tr>
              <th className="pb-2 font-medium">Área</th>
              <th className="pb-2 text-right font-medium">Trabajadores</th>
              <th className="w-1/3 pb-2 pl-6 font-medium">Solicitudes</th>
              <th className="pb-2 text-right font-medium">Diferencias</th>
              <th className="pb-2 text-right font-medium">Revisiones</th>
              <th className="pb-2 text-right font-medium">Pendientes</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {filas.map((f) => (
              <tr key={f.area}>
                <td className="py-2.5 font-medium">{f.area}</td>
                <td className="py-2.5 text-right tabular-nums">{f.trabajadores}</td>
                <td className="py-2.5 pl-6">
                  <div className="flex items-center gap-2">
                    <div className="flex h-2 flex-1 overflow-hidden rounded-full bg-slate-100">
                      <div className="bg-rose-400" style={{ width: `${(f.diferencias / maximo) * 100}%` }} />
                      <div className="bg-sky-400" style={{ width: `${(f.revisiones / maximo) * 100}%` }} />
                    </div>
                    <span className="w-6 text-right tabular-nums">{f.solicitudes}</span>
                  </div>
                </td>
                <td className="py-2.5 text-right tabular-nums">{f.diferencias}</td>
                <td className="py-2.5 text-right tabular-nums">{f.revisiones}</td>
                <td className="py-2.5 text-right font-medium tabular-nums">{f.pendientes || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="mt-3 flex gap-4 text-xs text-slate-500">
          <span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-rose-400" />Diferencia de cálculo</span>
          <span className="flex items-center gap-1.5"><span className="size-2 rounded-full bg-sky-400" />Revisión humana</span>
        </p>
      </Tarjeta>
    </div>
  )
}
