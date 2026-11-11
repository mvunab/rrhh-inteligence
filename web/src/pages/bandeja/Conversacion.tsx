import { useMutation, useQueryClient } from '@tanstack/react-query'
import { BatteryFull, Bot, CheckCheck, ChevronLeft, Mic, MoreVertical, Paperclip, Phone, Send,
  Signal, Smile, Video, Wifi } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import Markdown from '../../components/Markdown'
import { cn } from '../../components/ui'
import { api, type ItemBandeja } from '../../lib/api'

type Autor = 'trabajador' | 'agente' | 'rrhh'

interface Paso {
  autor: Autor
  cuando: string
  texto: string
  solicitud: string
}

function hilo(item: ItemBandeja): Paso[] {
  const pasos: Paso[] = []
  for (const s of item.solicitudes) {
    for (const m of s.mensajes) {
      pasos.push({ autor: 'trabajador', cuando: m.creado, texto: m.texto, solicitud: s.id })
      if (m.agente) pasos.push({ autor: 'agente', cuando: m.creado, texto: m.agente, solicitud: s.id })
    }
    if (s.estado === 'respondida' && s.respuesta) {
      pasos.push({ autor: 'rrhh', cuando: s.respondido ?? s.creado, texto: s.respuesta, solicitud: s.id })
    }
  }
  return pasos.sort((a, b) => a.cuando.localeCompare(b.cuando))
}

const ZONA = 'America/Santiago'

function horaCorta(iso: string): string {
  const fecha = new Date(iso)
  if (Number.isNaN(fecha.getTime())) return ''
  return fecha.toLocaleTimeString('es-CL', { timeZone: ZONA, hour: '2-digit', minute: '2-digit' })
}

function diaDe(iso: string): string {
  const fecha = new Date(iso)
  if (Number.isNaN(fecha.getTime())) return ''
  const clave = (d: Date) => d.toLocaleDateString('en-CA', { timeZone: ZONA })
  if (clave(fecha) === clave(new Date())) return 'HOY'
  return fecha.toLocaleDateString('es-CL', { timeZone: ZONA, day: 'numeric', month: 'short' }).toUpperCase()
}

const NOMBRE: Record<Autor, string> = { trabajador: '', agente: 'Agente', rrhh: 'RR.HH.' }

function etiquetaRrhh(item: ItemBandeja): string {
  const conNombre = item.solicitudes.map((s) => s.respondido_por).find(Boolean)
  return conNombre || 'RR.HH.'
}

export default function Conversacion({ item }: { item: ItemBandeja }) {
  const cliente = useQueryClient()
  const [respuesta, setRespuesta] = useState('')
  const fondo = useRef<HTMLDivElement>(null)
  const abiertas = item.solicitudes.filter((s) => s.estado === 'pendiente')
  const pasos = hilo(item)
  const responder = useMutation({
    mutationFn: async (texto: string) => {
      for (const s of abiertas) await api.responder(s.id, texto)
    },
    onSuccess: () => {
      setRespuesta('')
      toast.success('Respuesta enviada. El trabajador la ve en su chat.')
      cliente.invalidateQueries({ queryKey: ['bandeja'] })
    },
    onError: (e) => toast.error(e.message),
  })

  useEffect(() => {
    const caja = fondo.current
    if (caja) caja.scrollTop = caja.scrollHeight
  }, [pasos.length, item.id])

  const ahora = new Date().toLocaleTimeString('es-CL', { timeZone: ZONA, hour: '2-digit', minute: '2-digit' })
  const nombre = item.nombre.split(' ')[0]
  let diaPrevio = ''

  return (
    <div className="flex flex-col items-center">
      <div className="w-full max-w-3xl rounded-[1.6rem] border border-transparent bg-neutral-950 p-2 shadow-2xl ring-1 ring-black">
        <div className="flex h-[576px] flex-col overflow-hidden rounded-[calc(1.6rem-0.5rem-1px)] bg-[#efeae2]">
          <div className="relative flex items-center justify-between bg-[#075e54] px-4 py-1.5 text-[11px] font-medium text-white">
            <span>{ahora}</span>
            <span className="absolute left-1/2 size-1.5 -translate-x-1/2 rounded-full bg-black/80" />
            <span className="flex items-center gap-1">
              <Signal className="size-3" /><Wifi className="size-3" /><BatteryFull className="size-3.5" />
            </span>
          </div>

          <header className="flex items-center gap-2 bg-[#075e54] px-2 pt-1 pb-2 text-white">
            <ChevronLeft className="size-6 shrink-0" />
            <span className="grid size-9 shrink-0 place-items-center rounded-full bg-[#25d366] text-sm font-semibold">
              <Bot className="size-5" />
            </span>
            <div className="min-w-0 flex-1 leading-tight">
              <p className="truncate text-[15px] font-medium">Asistente de liquidaciones</p>
              <p className="text-[11px] text-emerald-100">en línea</p>
            </div>
            <Video className="size-5" /><Phone className="size-4" /><MoreVertical className="size-5" />
          </header>

          <div
            ref={fondo}
            className="min-h-0 flex-1 space-y-2 overflow-y-auto overscroll-contain bg-[radial-gradient(circle_at_12%_18%,rgba(0,0,0,.035)_1px,transparent_1.5px),radial-gradient(circle_at_72%_64%,rgba(0,0,0,.03)_1px,transparent_1.5px)] bg-[length:28px_28px] px-5 py-3"
          >
            <p className="mx-auto mb-2 max-w-md rounded-lg bg-[#fff3c4] px-3 py-1.5 text-center text-[12px] leading-snug text-[#546056] shadow-sm">
              {item.solicitudes.length
                ? `Chat de ${nombre}. Lo que escribas abajo le llega como respuesta de RR.HH.`
                : `${nombre} no ha escrito sobre esta liquidación. La detectó el sistema al cargar.`}
            </p>
            {pasos.map((paso, i) => {
              const dia = diaDe(paso.cuando)
              const separador = dia !== diaPrevio
              diaPrevio = dia
              const propio = paso.autor === 'trabajador'
              return (
                <div key={i}>
                  {separador && (
                    <p className="mx-auto my-2 w-fit rounded-lg bg-white/80 px-2.5 py-0.5 text-[11px] font-medium tracking-wide text-slate-500 shadow-sm">
                      {dia}
                    </p>
                  )}
                  <div className={cn('flex', propio ? 'justify-end' : 'justify-start')}>
                    <div className={cn('max-w-[70%] rounded-lg px-2.5 pt-1 pb-0.5 text-[14.5px] leading-snug shadow-sm',
                      propio ? 'rounded-tr-none bg-[#d9fdd3] text-slate-900' : 'rounded-tl-none bg-white text-slate-800')}>
                      {!propio && (
                        <p className={cn('text-[12px] font-semibold', paso.autor === 'agente' ? 'text-violet-700' : 'text-[#075e54]')}>
                          {paso.autor === 'rrhh' ? etiquetaRrhh(item) : NOMBRE[paso.autor]}
                        </p>
                      )}
                      {paso.autor === 'agente'
                        ? <div className="[&_li]:text-[14px] [&_p]:text-[14.5px]"><Markdown texto={paso.texto} /></div>
                        : <p className="whitespace-pre-wrap">{paso.texto}</p>}
                      <p className="mt-0.5 flex items-center justify-end gap-1 text-[10px] text-slate-500">
                        {horaCorta(paso.cuando)}
                        {propio && <CheckCheck className="size-3.5 text-[#53bdeb]" />}
                      </p>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault()
              if (respuesta.trim() && abiertas.length) responder.mutate(respuesta.trim())
            }}
            className="flex items-end gap-1.5 bg-[#f0f2f5] px-1.5 py-1.5"
          >
            <div className="flex min-w-0 flex-1 items-end gap-1.5 rounded-3xl bg-white px-2.5 py-1.5">
              <Smile className="mb-0.5 size-5 shrink-0 text-slate-500" />
              <textarea
                value={respuesta}
                rows={1}
                disabled={!abiertas.length || responder.isPending}
                onChange={(e) => setRespuesta(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && !e.shiftKey) {
                    e.preventDefault()
                    e.currentTarget.form?.requestSubmit()
                  }
                }}
                placeholder={abiertas.length ? 'Escribe un mensaje' : 'Conversación respondida'}
                className="max-h-24 min-h-6 w-full resize-none bg-transparent py-0.5 text-[14px] placeholder:text-slate-400 focus:outline-none disabled:placeholder:text-slate-400"
              />
              <Paperclip className="mb-0.5 size-5 shrink-0 text-slate-500" />
            </div>
            <button
              type="submit"
              disabled={!abiertas.length || !respuesta.trim() || responder.isPending}
              aria-label="Enviar"
              className="grid size-11 shrink-0 place-items-center rounded-full bg-[#00a884] text-white disabled:opacity-60"
            >
              {respuesta.trim() ? <Send className="size-5" /> : <Mic className="size-5" />}
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}
