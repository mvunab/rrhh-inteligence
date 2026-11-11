import { useQuery } from '@tanstack/react-query'
import { BarChart3, Inbox, Plug, Scale, Upload } from 'lucide-react'
import { type ReactNode } from 'react'
import { Navigate, NavLink, Route, Routes, useLocation } from 'react-router-dom'

import { cn } from './components/ui'
import { api } from './lib/api'
import { useToken } from './lib/sesion'
import Bandeja from './pages/Bandeja'
import Cargar from './pages/Cargar'
import Devengado from './pages/Devengado'
import Conectores from './pages/Conectores'
import Login from './pages/Login'
import Perfil from './pages/Perfil'
import Sectores from './pages/Sectores'

export default function App() {
  const token = useToken()
  const { pathname } = useLocation()

  if (!token && !pathname.startsWith('/login')) {
    return <Navigate to="/login" replace />
  }
  if (pathname.startsWith('/login')) {
    return (
      <div className="h-full bg-lienzo">
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="*" element={<Navigate to="/login" replace />} />
        </Routes>
      </div>
    )
  }

  return <Shell />
}

function Shell() {
  const { data: items } = useQuery({ queryKey: ['bandeja'], queryFn: api.bandeja })
  const { data: yo } = useQuery({ queryKey: ['yo'], queryFn: api.yo })
  const pendientes = items?.filter((i) => i.estado === 'pendiente').length ?? 0
  const secciones = [
    { a: '/bandeja', texto: 'Bandeja', icono: Inbox, aviso: pendientes },
    { a: '/devengado', texto: 'Devengado', icono: Scale },
    { a: '/sectores', texto: 'Sectores', icono: BarChart3 },
    { a: '/cargar', texto: 'Cargar', icono: Upload },
    { a: '/conectores', texto: 'Conectores', icono: Plug },
  ]

  return (
    <div className="flex h-full p-3 sm:p-4">
      <div className="flex min-h-0 min-w-0 flex-1 gap-3 overflow-hidden rounded-[2rem] bg-white p-3 shadow-[0_24px_60px_-28px_rgba(45,70,160,0.45)]">
        <aside className="flex h-full w-[4.25rem] shrink-0 flex-col items-center rounded-[1.6rem] bg-indigo-600 py-4 text-white">
          <div className="mb-6 grid size-10 place-items-center rounded-2xl bg-white text-sm font-bold text-indigo-600" title="RRHH Intelligence">
            R
          </div>
          <nav className="flex flex-1 flex-col items-center gap-1.5">
            {secciones.map(({ a, texto, icono: Icono, aviso }) => (
              <NavLink
                key={a}
                to={a}
                title={texto}
                aria-label={aviso ? `${texto}, ${aviso} pendientes` : texto}
                className={({ isActive }) => cn(
                  'relative grid size-11 place-items-center rounded-2xl transition-[background-color,color,transform] duration-200 ease-out',
                  isActive ? 'bg-white text-indigo-600' : 'text-white/90 hover:bg-white/15',
                )}
              >
                {({ isActive }) => (
                  <>
                    <Icono className={cn('size-5 transition-transform duration-200 ease-out', isActive && 'scale-105')} strokeWidth={1.75} />
                    <span className="sr-only">{texto}</span>
                    {!!aviso && (
                      <span className={cn('absolute -top-1 -right-1 grid min-w-4 place-items-center rounded-full px-1 text-[10px] font-bold',
                        isActive ? 'bg-indigo-600 text-white' : 'bg-white text-indigo-600')}>
                        {aviso}
                      </span>
                    )}
                  </>
                )}
              </NavLink>
            ))}
          </nav>
        </aside>
        <div className="flex min-h-0 min-w-0 flex-1 flex-col">
          <div className="flex shrink-0 items-center justify-end px-3 pt-1 pb-2">
            <NavLink
              to="/perfil"
              title="Tu perfil"
              className="presiona flex items-center gap-2 rounded-full py-1 pr-2 pl-1 text-sm text-slate-600 hover:bg-slate-50"
            >
              {yo?.avatar
                ? <img src={yo.avatar} alt="" className="size-9 rounded-full object-cover" />
                : <span className="grid size-9 place-items-center rounded-full bg-indigo-600 text-xs font-semibold text-white">
                    {iniciales(yo?.nombre ?? 'A')}
                  </span>}
              <span className="max-w-40 truncate font-medium">{yo?.nombre ?? '…'}</span>
            </NavLink>
          </div>
          <main className="min-h-0 flex-1">
            <Vista>
              <Routes>
                <Route path="/" element={<Navigate to="/bandeja" replace />} />
                <Route path="/bandeja" element={<Bandeja />} />
                <Route path="/bandeja/:itemId" element={<Bandeja />} />
                <Route path="/devengado" element={<Devengado />} />
                <Route path="/sectores" element={<Sectores />} />
                <Route path="/cargar" element={<Cargar />} />
                <Route path="/conectores" element={<Conectores />} />
                <Route path="/perfil" element={<Perfil />} />
                <Route path="/login" element={<Navigate to="/bandeja" replace />} />
              </Routes>
            </Vista>
          </main>
        </div>
      </div>
    </div>
  )
}

/** Anima al cambiar de sección del menú, no al elegir otro caso dentro de la bandeja. */
function Vista({ children }: { children: ReactNode }) {
  const { pathname } = useLocation()
  const seccion = pathname.split('/').filter(Boolean)[0] ?? 'bandeja'
  return (
    <div key={seccion} className="h-full min-h-0 animate-vista">
      {children}
    </div>
  )
}

function iniciales(nombre: string) {
  const partes = nombre.trim().split(/\s+/).filter(Boolean)
  return (partes[0]?.[0] ?? 'A').toUpperCase() + (partes[1]?.[0] ?? '').toUpperCase()
}
