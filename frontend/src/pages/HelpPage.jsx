import { useNavigate } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import manualMd from '../../../docs/user-manual.md?raw'
import Logo from '../components/Logo'

export default function HelpPage({ profile }) {
  const navigate = useNavigate()
  return (
    <div className="h-screen flex flex-col bg-ink-900">
      <header className="h-16 border-b border-ink-500/60 bg-ink-800/40 backdrop-blur flex items-center justify-between px-6">
        <div className="flex items-center gap-5">
          <button
            onClick={() => navigate(-1)}
            className="text-ink-300 hover:text-cream-100 transition-colors"
            title="Back"
          >
            <ArrowLeft size={18} />
          </button>
          <Logo size="md" />
          <span className="font-display italic text-sm text-cream-300 tracking-wide">
            User Manual
          </span>
        </div>
        <div className="text-xs text-cream-300">{profile?.email}</div>
      </header>

      <div className="flex-1 overflow-y-auto">
        <div className="max-w-3xl mx-auto px-6 py-10">
          <article className="prose-awm text-[15px] text-cream-100 leading-relaxed">
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{manualMd}</ReactMarkdown>
          </article>
        </div>
      </div>
    </div>
  )
}
