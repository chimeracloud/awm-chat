import { useState } from 'react'
import { signInWithGoogle } from '../lib/firebase'
import Logo from '../components/Logo'

export default function LoginPage() {
  const [error, setError] = useState(null)
  const [busy, setBusy] = useState(false)

  async function onSignIn() {
    setError(null)
    setBusy(true)
    try {
      await signInWithGoogle()
    } catch (e) {
      setError(e.message || 'Sign in failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="h-screen flex flex-col items-center justify-center px-6 animate-fade-in">
      {/* Decorative grain */}
      <div className="pointer-events-none absolute inset-0 opacity-[0.03]"
           style={{ backgroundImage: 'url("data:image/svg+xml;utf8,<svg xmlns=%22http://www.w3.org/2000/svg%22 width=%22200%22 height=%22200%22><filter id=%22n%22><feTurbulence baseFrequency=%220.9%22/></filter><rect width=%22200%22 height=%22200%22 filter=%22url(%23n)%22/></svg>")' }}
      />

      <div className="relative w-full max-w-sm">
        <div className="flex flex-col items-center mb-12">
          <Logo size="lg" />
          <p className="font-display italic text-cream-300 text-sm mt-4 tracking-wide">
            Internal intelligence platform
          </p>
        </div>

        <div className="bg-ink-800/60 backdrop-blur border border-ink-500/60 rounded-lg p-8 shadow-2xl">
          <h2 className="font-display text-2xl text-cream-50 tracking-tightest mb-2">Sign in</h2>
          <p className="text-sm text-cream-300 mb-6 leading-relaxed">
            Access restricted to <span className="text-gold-500">@ascotwm.com</span> Workspace accounts.
          </p>

          <button
            onClick={onSignIn}
            disabled={busy}
            className="w-full bg-cream-50 hover:bg-white text-ink-900 font-medium py-3 px-4 rounded-md transition-colors disabled:opacity-50 flex items-center justify-center gap-3"
          >
            <svg width="18" height="18" viewBox="0 0 18 18">
              <path fill="#4285F4" d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844a4.14 4.14 0 01-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z"/>
              <path fill="#34A853" d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 009 18z"/>
              <path fill="#FBBC05" d="M3.964 10.71A5.41 5.41 0 013.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 000 9c0 1.452.348 2.827.957 4.042l3.007-2.332z"/>
              <path fill="#EA4335" d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 00.957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z"/>
            </svg>
            {busy ? 'Signing in...' : 'Continue with Google'}
          </button>

          {error && (
            <div className="mt-4 p-3 bg-accent-danger/10 border border-accent-danger/30 rounded text-sm text-accent-danger">
              {error}
            </div>
          )}
        </div>

        <p className="text-center text-xs text-ink-300 mt-8">
          By signing in you accept that conversations are company property and subject to compliance review.
        </p>
      </div>
    </div>
  )
}
