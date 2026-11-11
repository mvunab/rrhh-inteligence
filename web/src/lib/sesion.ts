import { useSyncExternalStore } from 'react'

const CLAVE = 'rrhh.token'
const oyentes = new Set<() => void>()

function avisar() {
  oyentes.forEach((oyente) => oyente())
}

export function leerToken(): string | null {
  return localStorage.getItem(CLAVE)
}

export function guardarToken(token: string | null): void {
  if (token) localStorage.setItem(CLAVE, token)
  else localStorage.removeItem(CLAVE)
  avisar()
}

export function useToken(): string | null {
  return useSyncExternalStore(
    (oyente) => {
      oyentes.add(oyente)
      return () => oyentes.delete(oyente)
    },
    leerToken,
  )
}
