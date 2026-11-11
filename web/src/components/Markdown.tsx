import { Fragment, type ReactNode } from 'react'

// Lo justo para las respuestas del agente: párrafos, listas con "-" o "*" y **negrita**.
function enLinea(texto: string): ReactNode[] {
  return texto.split(/(\*\*[^*]+\*\*)/g).map((parte, i) =>
    parte.startsWith('**') && parte.endsWith('**')
      ? <strong key={i} className="font-semibold">{parte.slice(2, -2)}</strong>
      : <Fragment key={i}>{parte}</Fragment>)
}

export default function Markdown({ texto }: { texto: string }) {
  const bloques: ReactNode[] = []
  let lista: string[] = []
  const cerrarLista = () => {
    if (lista.length) {
      bloques.push(
        <ul key={`l${bloques.length}`} className="ml-4 list-disc space-y-1">
          {lista.map((item, i) => <li key={i}>{enLinea(item)}</li>)}
        </ul>,
      )
      lista = []
    }
  }
  for (const linea of texto.split('\n')) {
    const limpia = linea.trim()
    if (/^[-*]\s+/.test(limpia)) {
      lista.push(limpia.replace(/^[-*]\s+/, ''))
      continue
    }
    cerrarLista()
    if (limpia) bloques.push(<p key={`p${bloques.length}`}>{enLinea(limpia)}</p>)
  }
  cerrarLista()
  return <div className="space-y-2">{bloques}</div>
}
