import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Camera, LogOut } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { Boton, Cargando, Entrada, Rotulo, Tarjeta } from '../components/ui'
import { api } from '../lib/api'
import { guardarToken } from '../lib/sesion'

function iniciales(nombre: string) {
  const partes = nombre.trim().split(/\s+/).filter(Boolean)
  return (partes[0]?.[0] ?? 'A').toUpperCase() + (partes[1]?.[0] ?? '').toUpperCase()
}

export default function Perfil() {
  const cliente = useQueryClient()
  const navegar = useNavigate()
  const { data: yo, isLoading } = useQuery({ queryKey: ['yo'], queryFn: api.yo })
  const [nombre, setNombre] = useState<string | null>(null)
  const [cargo, setCargo] = useState<string | null>(null)
  const [area, setArea] = useState<string | null>(null)
  const [telefono, setTelefono] = useState<string | null>(null)

  const guardar = useMutation({
    mutationFn: () => api.actualizarPerfil({
      nombre: nombre ?? yo!.nombre,
      cargo: cargo ?? yo!.cargo,
      area: area ?? yo!.area,
      telefono: telefono ?? yo!.telefono,
    }),
    onSuccess: (perfil) => {
      cliente.setQueryData(['yo'], perfil)
      toast.success('Perfil actualizado.')
    },
    onError: (e: Error) => toast.error(e.message),
  })

  const avatar = useMutation({
    mutationFn: (archivo: File) => api.subirAvatar(archivo),
    onSuccess: (perfil) => {
      cliente.setQueryData(['yo'], perfil)
      toast.success('Avatar actualizado.')
    },
    onError: (e: Error) => toast.error(e.message),
  })

  async function salir() {
    try { await api.logout() } catch { /* da igual */ }
    guardarToken(null)
    cliente.clear()
    navegar('/login', { replace: true })
  }

  if (isLoading || !yo) return <Cargando />

  return (
    <div className="mx-auto h-full max-w-2xl space-y-6 overflow-y-auto overscroll-contain p-6">
      <div>
        <h1 className="text-[1.65rem] font-bold tracking-tight text-slate-900">Tu perfil</h1>
        <p className="text-sm text-slate-500">Así quedás en la bitácora de cada caso y emisión.</p>
      </div>

      <Tarjeta>
        <div className="flex flex-wrap items-center gap-5">
          <div className="relative">
            {yo.avatar
              ? <img src={yo.avatar} alt="" className="size-20 rounded-full object-cover ring-2 ring-indigo-100" />
              : <span className="grid size-20 place-items-center rounded-full bg-indigo-600 text-xl font-semibold text-white">
                  {iniciales(yo.nombre)}
                </span>}
            <label className="presiona absolute -right-1 -bottom-1 grid size-8 cursor-pointer place-items-center rounded-full bg-white text-slate-600 shadow ring-1 ring-slate-200 hover:bg-slate-50">
              <Camera className="size-4" />
              <input type="file" accept="image/png,image/jpeg,image/webp" className="sr-only"
                onChange={(e) => {
                  const f = e.target.files?.[0]
                  if (f) avatar.mutate(f)
                  e.target.value = ''
                }} />
            </label>
          </div>
          <div className="min-w-0">
            <p className="truncate text-lg font-semibold text-slate-900">{yo.nombre}</p>
            <p className="truncate text-sm text-slate-500">{yo.email}</p>
            {(yo.cargo || yo.area) && (
              <p className="mt-1 text-sm text-slate-500">
                {[yo.cargo, yo.area].filter(Boolean).join(' · ')}
              </p>
            )}
          </div>
        </div>
      </Tarjeta>

      <Tarjeta titulo="Datos personales">
        <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); guardar.mutate() }}>
          <Rotulo texto="Nombre">
            <Entrada value={nombre ?? yo.nombre} onChange={(e) => setNombre(e.target.value)} required />
          </Rotulo>
          <Rotulo texto="Correo" ayuda="El correo no se cambia desde aquí.">
            <Entrada value={yo.email} disabled />
          </Rotulo>
          <div className="grid gap-4 sm:grid-cols-2">
            <Rotulo texto="Cargo">
              <Entrada value={cargo ?? yo.cargo} onChange={(e) => setCargo(e.target.value)}
                placeholder="Analista de remuneraciones" />
            </Rotulo>
            <Rotulo texto="Área">
              <Entrada value={area ?? yo.area} onChange={(e) => setArea(e.target.value)}
                placeholder="Recursos Humanos" />
            </Rotulo>
          </div>
          <Rotulo texto="Teléfono">
            <Entrada value={telefono ?? yo.telefono} onChange={(e) => setTelefono(e.target.value)}
              placeholder="+56 9 …" />
          </Rotulo>
          <div className="flex flex-wrap gap-2 pt-1">
            <Boton variante="primario" type="submit" cargando={guardar.isPending}>Guardar</Boton>
            <Boton type="button" onClick={salir}>
              <LogOut className="size-4" /> Cerrar sesión
            </Boton>
          </div>
        </form>
      </Tarjeta>
    </div>
  )
}
