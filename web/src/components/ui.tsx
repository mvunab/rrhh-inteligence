import { clsx, type ClassValue } from 'clsx'
import { Loader2 } from 'lucide-react'
import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode, SelectHTMLAttributes,
  TextareaHTMLAttributes } from 'react'
import { twMerge } from 'tailwind-merge'

export function cn(...clases: ClassValue[]) {
  return twMerge(clsx(clases))
}

type Variante = 'primario' | 'secundario' | 'fantasma' | 'peligro'

const VARIANTES: Record<Variante, string> = {
  primario: 'bg-indigo-600 text-white hover:bg-indigo-500 shadow-sm shadow-indigo-600/20',
  secundario: 'bg-white text-slate-700 ring-1 ring-slate-200 hover:bg-slate-50 shadow-sm',
  fantasma: 'text-slate-600 hover:bg-slate-100',
  peligro: 'bg-rose-600 text-white hover:bg-rose-500 shadow-sm',
}

export function estiloBoton(variante: Variante = 'secundario', className?: string, estatico = false) {
  return cn('inline-flex items-center justify-center gap-1.5 rounded-xl border border-transparent px-3.5 py-2 text-sm font-medium',
    'disabled:cursor-not-allowed disabled:opacity-50', !estatico && 'presiona', VARIANTES[variante], className)
}

export function Boton({ variante = 'secundario', cargando, estatico, className, children, disabled, ...resto }:
  ButtonHTMLAttributes<HTMLButtonElement> & { variante?: Variante; cargando?: boolean; estatico?: boolean }) {
  return (
    <button
      {...resto}
      disabled={disabled || cargando}
      className={estiloBoton(variante, className, estatico)}
    >
      {cargando && <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />}
      {children}
    </button>
  )
}

type Tono = 'gris' | 'rojo' | 'ambar' | 'verde' | 'azul' | 'indigo'

const TONOS: Record<Tono, string> = {
  gris: 'bg-slate-100 text-slate-700 ring-slate-200',
  rojo: 'bg-rose-50 text-rose-700 ring-rose-200',
  ambar: 'bg-amber-50 text-amber-800 ring-amber-200',
  verde: 'bg-emerald-50 text-emerald-700 ring-emerald-200',
  azul: 'bg-sky-50 text-sky-700 ring-sky-200',
  indigo: 'bg-indigo-50 text-indigo-700 ring-indigo-200',
}

export function Etiqueta({ tono = 'gris', children, className }: { tono?: Tono; children: ReactNode;
  className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-1 rounded-full border border-transparent px-2 py-0.5 text-xs font-medium ring-1 ring-inset',
      TONOS[tono], className)}>
      {children}
    </span>
  )
}

export function Tarjeta({ titulo, accion, children, className }: { titulo?: ReactNode; accion?: ReactNode;
  children: ReactNode; className?: string }) {
  return (
    <section className={cn('rounded-2xl border border-slate-100 bg-white shadow-[0_10px_30px_-18px_rgba(40,60,120,0.45)]', className)}>
      {(titulo || accion) && (
        <header className="flex items-center justify-between gap-3 border-b border-slate-100 px-5 py-3">
          <h3 className="text-sm font-semibold text-slate-800">{titulo}</h3>
          {accion}
        </header>
      )}
      <div className="p-5">{children}</div>
    </section>
  )
}

const CAMPO = 'w-full rounded-xl border border-slate-200 bg-white px-3 py-2 text-sm placeholder:text-slate-400 focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/30 focus:outline-none'

export function Entrada(props: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={cn(CAMPO, props.className)} />
}

export function Texto(props: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={cn(CAMPO, 'min-h-20', props.className)} />
}

export function Selector(props: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...props} className={cn(CAMPO, 'pr-8', props.className)} />
}

export function Rotulo({ texto, ayuda, children }: { texto: string; ayuda?: string; children: ReactNode }) {
  return (
    <label className="block space-y-1">
      <span className="text-xs font-medium text-slate-600">{texto}</span>
      {children}
      {ayuda && <span className="block text-xs text-slate-400">{ayuda}</span>}
    </label>
  )
}

export function Cargando({ texto = 'Cargando…' }: { texto?: string }) {
  return (
    <div className="flex items-center gap-2 p-6 text-sm text-slate-500">
      <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> {texto}
    </div>
  )
}

export function Vacio({ icono, titulo, children }: { icono?: ReactNode; titulo: string; children?: ReactNode }) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 p-10 text-center">
      {icono && <div className="text-slate-300">{icono}</div>}
      <p className="font-medium text-slate-700">{titulo}</p>
      {children && <p className="max-w-sm text-sm text-slate-500">{children}</p>}
    </div>
  )
}

export function Pestanas<T extends string>({ valor, opciones, onCambio }: {
  valor: T; opciones: { id: T; texto: ReactNode; aviso?: ReactNode }[]; onCambio: (id: T) => void }) {
  return (
    <nav className="flex flex-wrap gap-1">
      {opciones.map((o) => (
        <button
          key={o.id}
          onClick={() => onCambio(o.id)}
          className={cn('flex items-center gap-1.5 whitespace-nowrap rounded-xl px-3 py-2 text-sm font-medium transition-colors duration-150',
            valor === o.id ? 'bg-indigo-50 text-indigo-700' : 'text-slate-500 hover:bg-slate-50 hover:text-slate-800')}
        >
          {o.texto}
          {o.aviso}
        </button>
      ))}
    </nav>
  )
}

export function Segmentos<T extends string>({ valor, opciones, onCambio }: {
  valor: T; opciones: { id: T; texto: string }[]; onCambio: (id: T) => void }) {
  return (
    <div className="inline-flex rounded-xl bg-slate-100 p-1">
      {opciones.map((o) => (
        <button
          key={o.id}
          onClick={() => onCambio(o.id)}
          className={cn('rounded-lg border border-transparent px-3 py-1 text-xs font-medium transition-colors duration-150',
            valor === o.id ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-500 hover:text-slate-800')}
        >
          {o.texto}
        </button>
      ))}
    </div>
  )
}

export function Cifra({ etiqueta, valor, detalle, tono }: { etiqueta: string; valor: ReactNode;
  detalle?: ReactNode; tono?: 'verde' | 'rojo' }) {
  return (
    <div>
      <p className="text-xs font-medium text-slate-400">{etiqueta}</p>
      <p className="mt-1 text-3xl font-bold tracking-tight tabular-nums text-slate-900">{valor}</p>
      {detalle && (
        <p className={cn('text-xs font-medium tabular-nums',
          tono === 'verde' ? 'text-emerald-600' : tono === 'rojo' ? 'text-rose-600' : 'text-slate-500')}>
          {detalle}
        </p>
      )}
    </div>
  )
}
