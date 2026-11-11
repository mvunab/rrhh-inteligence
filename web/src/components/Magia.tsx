import { Sparkles } from 'lucide-react'
import { useEffect } from 'react'

import type { Borrador } from '../lib/api'
import { clp, delta } from '../lib/formato'
import { Boton, cn } from './ui'

export type FaseMagia = 'varita' | 'conejo'

const DESTELLOS = [
  { x: '12%', y: '30%', d: '0s', t: 'size-4' },
  { x: '80%', y: '6%', d: '0.4s', t: 'size-4' },
  { x: '24%', y: '8%', d: '0.8s', t: 'size-3' },
]

function Sombrero({ salto }: { salto: boolean }) {
  return (
    <svg viewBox="0 0 200 160" className={cn('w-[150px] origin-bottom', salto && 'animate-sombrero')} aria-hidden>
      <path d="M42 24 L52 132 L148 132 L158 24 Z" fill="#18181b" />
      <path d="M42 24 L52 132 L70 132 L62 24 Z" fill="#27272a" />
      <path d="M49 100 L51 122 L149 122 L151 100 Z" fill="#7c3aed" />
      <path d="M49 100 L51 106 L149 106 L151 100 Z" fill="#a78bfa" />
      <ellipse cx="100" cy="24" rx="58" ry="11" fill="#09090b" />
      <ellipse cx="100" cy="24" rx="58" ry="11" fill="none" stroke="#3f3f46" strokeWidth="3" />
      <ellipse cx="100" cy="138" rx="96" ry="18" fill="#09090b" />
      <ellipse cx="100" cy="134" rx="96" ry="16" fill="#27272a" />
    </svg>
  )
}

function Conejo() {
  return (
    <svg viewBox="0 0 120 150" className="w-[84px]" aria-hidden>
      <ellipse cx="42" cy="38" rx="12" ry="34" fill="#fafafa" transform="rotate(-8 42 38)" />
      <ellipse cx="42" cy="40" rx="6" ry="25" fill="#fbcfe8" transform="rotate(-8 42 40)" />
      <ellipse cx="78" cy="38" rx="12" ry="34" fill="#fafafa" transform="rotate(10 78 38)" />
      <ellipse cx="78" cy="40" rx="6" ry="25" fill="#fbcfe8" transform="rotate(10 78 40)" />
      <ellipse cx="60" cy="112" rx="40" ry="40" fill="#fafafa" />
      <circle cx="46" cy="102" r="5" fill="#18181b" />
      <circle cx="74" cy="102" r="5" fill="#18181b" />
      <circle cx="47.5" cy="100.5" r="1.6" fill="#fff" />
      <circle cx="75.5" cy="100.5" r="1.6" fill="#fff" />
      <circle cx="36" cy="116" r="6" fill="#fbcfe8" opacity="0.8" />
      <circle cx="84" cy="116" r="6" fill="#fbcfe8" opacity="0.8" />
      <path d="M56 113 L64 113 L60 118 Z" fill="#f472b6" />
      <path d="M60 118 Q55 125 50 122 M60 118 Q65 125 70 122" stroke="#18181b" strokeWidth="1.6" fill="none"
        strokeLinecap="round" />
      <path d="M44 117 L22 113 M44 120 L22 122 M76 117 L98 113 M76 120 L98 122" stroke="#a1a1aa" strokeWidth="1.2"
        strokeLinecap="round" />
      <ellipse cx="38" cy="146" rx="11" ry="7" fill="#f4f4f5" stroke="#d4d4d8" />
      <ellipse cx="82" cy="146" rx="11" ry="7" fill="#f4f4f5" stroke="#d4d4d8" />
    </svg>
  )
}

function Varita() {
  return (
    <svg viewBox="0 0 110 110" className="w-[76px] origin-bottom-left animate-varita" aria-hidden>
      <line x1="8" y1="102" x2="92" y2="18" stroke="#18181b" strokeWidth="9" strokeLinecap="round" />
      <line x1="76" y1="34" x2="92" y2="18" stroke="#fafafa" strokeWidth="9" strokeLinecap="round" />
      <path d="M98 2 L101 11 L110 14 L101 17 L98 26 L95 17 L86 14 L95 11 Z" fill="#fde047" />
    </svg>
  )
}

export default function Magia({ fase, borrador, onVer }: {
  fase: FaseMagia; borrador?: Borrador; onVer: () => void }) {
  const salio = fase === 'conejo' && !!borrador

  useEffect(() => {
    if (!salio) return
    const tecla = (e: KeyboardEvent) => e.key === 'Escape' && onVer()
    window.addEventListener('keydown', tecla)
    return () => window.removeEventListener('keydown', tecla)
  }, [salio, onVer])

  const antes = borrador?.original.liquido_a_pagar ?? 0
  const despues = borrador?.propuesta.liquido_a_pagar ?? 0
  const diferencia = despues - antes
  const cambios = (borrador?.ajustes ?? []).filter((a) => !a.concepto.toLowerCase().startsWith('líquido'))

  return (
    <div role="dialog" aria-modal aria-label="Generando la propuesta corregida"
      className="absolute inset-0 z-20 animate-velo bg-slate-50/80 backdrop-blur-[2px] motion-reduce:backdrop-blur-none">
      <div className="sticky top-0 flex flex-col items-center pt-16">
        <div className="relative h-[230px] w-[210px]">
          {DESTELLOS.map((s) => (
            <Sparkles key={s.x + s.y} className={cn('absolute animate-destello text-amber-400/80', s.t)}
              style={{ left: s.x, top: s.y, animationDelay: s.d }} />
          ))}

          {/* El conejo sube desde la boca del sombrero: el recorte termina justo en la copa. */}
          <div className="absolute left-1/2 top-0 h-[128px] w-[100px] -translate-x-1/2 overflow-hidden">
            {salio && (
              <div className="absolute bottom-0 left-1/2 -translate-x-1/2">
                <div className="animate-conejo motion-reduce:animate-none"><Conejo /></div>
              </div>
            )}
          </div>

          <div className="absolute bottom-0 left-1/2 -translate-x-1/2"><Sombrero salto={salio} /></div>

          {salio && [0, 0.12, 0.24].map((d, i) => (
            <span key={d} className="absolute size-16 animate-humo rounded-full bg-violet-200/50 blur-md"
              style={{ left: `${40 + i * 10}%`, top: '56%', animationDelay: `${d}s` }} />
          ))}

          <div className={cn('absolute right-0 top-[48px] transition-[translate,opacity] duration-150 ease-out motion-reduce:transition-opacity',
            salio && '-translate-y-3 opacity-0')}>
            <Varita />
          </div>
        </div>

        {salio ? (
          <div className="mt-3 w-[300px] animate-aparecer rounded-xl border border-transparent bg-white p-4 text-center shadow-lg
            ring-1 ring-slate-200 [animation-delay:0.55s]">
            <p className="text-[11px] font-semibold uppercase tracking-wider text-violet-600">Corrección lista</p>
            <div className="mt-2 flex items-baseline justify-center gap-3 tabular-nums">
              <span className="text-sm text-slate-400 line-through">{clp(antes)}</span>
              <span className="text-xl font-semibold text-slate-900">{clp(despues)}</span>
            </div>
            <p className={cn('mt-1 text-sm font-medium',
              diferencia > 0 ? 'text-emerald-600' : diferencia < 0 ? 'text-rose-600' : 'text-slate-500')}>
              {diferencia === 0 ? 'El líquido no cambia' : `${delta(diferencia)} en el líquido`}
            </p>
            {cambios.length > 0 && (
              <ul className="mt-3 space-y-1 text-left text-xs text-slate-600">
                {cambios.slice(0, 3).map((a) => (
                  <li key={a.concepto} className="flex justify-between gap-3">
                    <span className="truncate">{a.concepto}</span>
                    <span className="shrink-0 tabular-nums">{clp(a.emitido)} → {clp(a.propuesto)}</span>
                  </li>
                ))}
              </ul>
            )}
            <Boton variante="primario" className="mt-3 w-full" onClick={onVer} autoFocus>
              Ver la corrección
            </Boton>
          </div>
        ) : (
          <p className="mt-5 animate-flotar text-sm text-slate-500">
            Abracadabra… el motor recalcula con el contrato vigente
          </p>
        )}
      </div>
    </div>
  )
}
