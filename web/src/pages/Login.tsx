import { type FormEvent, useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { Boton, Entrada, Rotulo } from '../components/ui'
import { api } from '../lib/api'
import { guardarToken, useToken } from '../lib/sesion'

export default function Login() {
  const token = useToken()
  const navegar = useNavigate()
  const [email, setEmail] = useState('analista@clinica.local')
  const [password, setPassword] = useState('')
  const [cargando, setCargando] = useState(false)

  if (token) return <Navigate to="/bandeja" replace />

  async function enviar(e: FormEvent) {
    e.preventDefault()
    setCargando(true)
    try {
      const { token: nuevo } = await api.login(email.trim(), password)
      guardarToken(nuevo)
      navegar('/bandeja', { replace: true })
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'No se pudo iniciar sesión')
    } finally {
      setCargando(false)
    }
  }

  return (
    <div className="flex h-full items-center justify-center p-6">
      <form onSubmit={enviar}
        className="w-full max-w-sm space-y-5 rounded-[1.6rem] bg-white p-8 shadow-[0_24px_60px_-28px_rgba(45,70,160,0.45)]">
        <div className="space-y-1">
          <div className="mb-4 grid size-11 place-items-center rounded-2xl bg-indigo-600 text-sm font-bold text-white">R</div>
          <h1 className="text-xl font-bold tracking-tight text-slate-900">Centro de RR.HH.</h1>
          <p className="text-sm text-slate-500">Entrá con tu correo de analista.</p>
        </div>
        <Rotulo texto="Correo">
          <Entrada type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required />
        </Rotulo>
        <Rotulo texto="Contraseña">
          <Entrada type="password" autoComplete="current-password" value={password}
            onChange={(e) => setPassword(e.target.value)} required />
        </Rotulo>
        <Boton variante="primario" type="submit" cargando={cargando} className="w-full">
          Entrar
        </Boton>
        <p className="text-center text-xs text-slate-400">
          Demo: analista@clinica.local · analista123
        </p>
      </form>
    </div>
  )
}
