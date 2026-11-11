import { ArrowDown, ArrowUp } from 'lucide-react'

import { cn } from '../../components/ui'
import type { Diff } from '../../lib/api'
import { clp, delta } from '../../lib/formato'

export function EnSimple({ diff }: { diff: Diff }) {
  const s = diff.en_simple
  const sube = s.liquido_despues - s.liquido_antes
  const explicados = new Set<string>()
  return (
    <div className="space-y-4">
      <div>
        <p className="text-[11px] font-semibold tracking-wider text-slate-400 uppercase">En simple</p>
        <p className="mt-1 text-lg font-semibold text-slate-900">{s.titular}</p>
      </div>
      <div className="flex items-center gap-3 rounded-lg border border-transparent bg-slate-50 px-4 py-3 ring-1 ring-slate-100">
        <div>
          <p className="text-xs text-slate-500">{diff.etiquetas[0]}</p>
          <p className="text-base font-semibold tabular-nums text-slate-500 line-through decoration-slate-300">
            {clp(s.liquido_antes)}
          </p>
        </div>
        <span className="text-slate-300">→</span>
        <div>
          <p className="text-xs text-slate-500">{diff.etiquetas[1]}</p>
          <p className="text-base font-semibold tabular-nums">{clp(s.liquido_despues)}</p>
        </div>
        <span className={cn('ml-auto rounded-full px-2 py-0.5 text-sm font-semibold tabular-nums',
          sube > 0 ? 'bg-emerald-50 text-emerald-700' : sube < 0 ? 'bg-rose-50 text-rose-700' : 'bg-slate-100 text-slate-600')}>
          {delta(sube)}
        </span>
      </div>
      <ul className="space-y-3">
        {s.puntos.map((p, i) => {
          const nuevo = p.por_que && !explicados.has(p.por_que)
          if (p.por_que) explicados.add(p.por_que)
          return (
            <li key={i} className="flex gap-2.5">
              <span className={cn('mt-0.5 grid size-5 shrink-0 place-items-center rounded-full',
                p.favorece_al_trabajador ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-700')}>
                {p.favorece_al_trabajador ? <ArrowUp className="size-3" /> : <ArrowDown className="size-3" />}
              </span>
              <div className="text-sm leading-relaxed text-slate-700">
                <p dangerouslySetInnerHTML={{ __html: negritas(p.texto) }} />
                {nuevo && <p className="mt-0.5 text-xs text-slate-500">Por qué: {p.por_que}</p>}
              </div>
            </li>
          )
        })}
      </ul>
      <p className="text-xs text-slate-400">
        {s.pie} Verde: el cambio favorece al trabajador. Rojo: lo perjudica.
      </p>
    </div>
  )
}

function negritas(texto: string): string {
  const seguro = texto.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  return seguro.replace(/\*\*([^*]+)\*\*/g, '<strong class="font-semibold text-slate-900">$1</strong>')
}

export function DiffTecnico({ diff }: { diff: Diff }) {
  const lineas = diff.texto.split('\n')
  const agregadas = lineas.filter((l) => l.startsWith('+ ')).length
  const quitadas = lineas.filter((l) => l.startsWith('- ')).length
  return (
    <div className="overflow-hidden rounded-lg border border-transparent ring-1 ring-slate-200">
      <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-3 py-2 text-xs">
        <span className="font-mono text-slate-600">{diff.etiquetas[0]} → {diff.etiquetas[1]}</span>
        <span className="font-mono">
          <span className="text-emerald-600">+{agregadas}</span> <span className="text-rose-600">−{quitadas}</span>
        </span>
      </div>
      <div className="overflow-x-auto overscroll-x-contain bg-white font-mono text-[12.5px] leading-6">
        {lineas.slice(2).map((linea, i) => {
          const tipo = linea.startsWith('@@') ? 'seccion' : linea[0] === '+' ? 'mas' : linea[0] === '-' ? 'menos' : 'igual'
          return (
            <div key={i} className={cn('flex whitespace-pre',
              tipo === 'seccion' && 'bg-sky-50 text-sky-700',
              tipo === 'mas' && 'bg-emerald-50 text-emerald-900',
              tipo === 'menos' && 'bg-rose-50 text-rose-900',
              tipo === 'igual' && 'text-slate-500')}>
              <span className={cn('w-8 shrink-0 select-none text-center',
                tipo === 'mas' && 'bg-emerald-100 text-emerald-600',
                tipo === 'menos' && 'bg-rose-100 text-rose-600')}>
                {tipo === 'mas' ? '+' : tipo === 'menos' ? '−' : ''}
              </span>
              <span className="pr-4">{tipo === 'seccion' ? linea.replace(/@@/g, '').trim() : linea.slice(2)}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}
