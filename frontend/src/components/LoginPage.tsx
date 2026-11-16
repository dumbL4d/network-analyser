import { Eye, EyeOff, KeyRound, ShieldCheck, UserRound } from 'lucide-react'
import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useAuth } from '@/contexts/AuthContext'

function NetworkPreview() {
  return (
    <div className="relative mt-10 h-[310px] w-full max-w-md">
      <div className="absolute inset-0 rounded-2xl border border-white/10 bg-white/[0.035]" />
      <div className="hairline-grid absolute inset-0 rounded-2xl opacity-[0.18]" />
      <div className="absolute left-8 top-8 flex items-center gap-2 text-[10px] font-medium uppercase tracking-[0.14em] text-slate-400">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
        Live topology
      </div>

      <div className="absolute left-[18%] top-[44%] h-px w-[24%] bg-gradient-to-r from-slate-500/20 to-slate-400/50" />
      <div className="absolute left-[48%] top-[36%] h-[20%] w-px bg-gradient-to-b from-slate-400/50 to-slate-500/10" />
      <div className="absolute left-[48%] top-[58%] h-px w-[24%] bg-gradient-to-r from-slate-400/50 to-slate-500/20" />
      <div className="absolute left-[48%] top-[36%] h-px w-[24%] bg-gradient-to-r from-slate-400/50 to-slate-500/20" />
      <div className="absolute left-[66%] top-[36%] h-[22%] w-px bg-gradient-to-b from-slate-400/40 to-slate-500/5" />
      <div className="absolute left-[66%] top-[58%] h-px w-[16%] bg-slate-400/30" />

      {[
        { label: 'EDGE', x: '7%', y: '35%', tone: 'border-blue-400/40 bg-blue-400/10 text-blue-200' },
        { label: 'CORE', x: '42%', y: '24%', tone: 'border-emerald-400/40 bg-emerald-400/10 text-emerald-200' },
        { label: 'OT', x: '42%', y: '49%', tone: 'border-violet-400/40 bg-violet-400/10 text-violet-200' },
        { label: 'SRV', x: '70%', y: '24%', tone: 'border-slate-400/40 bg-slate-400/10 text-slate-200' },
        { label: 'PLC', x: '70%', y: '49%', tone: 'border-amber-400/40 bg-amber-400/10 text-amber-200' },
      ].map((node) => (
        <div
          key={node.label}
          className={`absolute flex h-11 w-[72px] flex-col justify-center rounded-lg border px-2.5 shadow-lg ${node.tone}`}
          style={{ left: node.x, top: node.y }}
        >
          <span className="text-[9px] font-semibold tracking-[0.12em]">
            {node.label}
          </span>
          <span className="mt-1 h-1 w-8 rounded-full bg-current opacity-25" />
        </div>
      ))}

      <div className="absolute bottom-8 left-8 right-8 flex items-center justify-between border-t border-white/10 pt-4">
        <div>
          <p className="text-[9px] font-medium uppercase tracking-[0.14em] text-slate-500">
            Root cause
          </p>
          <p className="mono mt-1 text-xs text-slate-300">sw-edge-2</p>
        </div>
        <div className="text-right">
          <p className="text-[9px] font-medium uppercase tracking-[0.14em] text-slate-500">
            Blast radius
          </p>
          <p className="mono mt-1 text-xs text-rose-300">4 devices</p>
        </div>
      </div>
    </div>
  )
}

export default function LoginPage() {
  const { login } = useAuth()
  const navigate = useNavigate()

  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    setSubmitting(true)
    setError(null)
    try {
      await login(username, password)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Login failed')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="grid min-h-screen bg-white lg:grid-cols-[1.05fr_0.95fr]">
      <section className="relative hidden overflow-hidden bg-slate-950 text-white lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div className="absolute -left-32 -top-40 h-[440px] w-[440px] rounded-full bg-blue-600/15 blur-3xl" />
        <div className="absolute -bottom-40 right-0 h-[380px] w-[380px] rounded-full bg-violet-600/10 blur-3xl" />

        <div className="relative flex items-center gap-3">
          <span className="relative flex h-9 w-9 items-center justify-center rounded-[10px] border border-white/15 bg-white/10">
            <ShieldCheck className="h-[18px] w-[18px]" />
            <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full border-2 border-slate-950 bg-emerald-400" />
          </span>
          <div>
            <p className="text-sm font-semibold tracking-tight">
              Network Analyser
            </p>
            <p className="mt-0.5 text-[9px] font-medium uppercase tracking-[0.16em] text-slate-500">
              OT observability
            </p>
          </div>
        </div>

        <div className="relative">
          <span className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-3 py-1 text-[10px] font-medium uppercase tracking-[0.12em] text-slate-400">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
            Topology-aware monitoring
          </span>
          <h1 className="mt-6 max-w-lg text-[38px] font-semibold leading-[1.12] tracking-[-0.03em] text-white">
            Find the device that actually failed.
          </h1>
          <p className="mt-4 max-w-md text-[13px] leading-relaxed text-slate-400">
            Separate root causes from collateral damage, quantify blast radius,
            and resolve outages with a clear operational timeline.
          </p>
          <NetworkPreview />
        </div>

        <div className="relative flex items-center justify-between text-[10px] uppercase tracking-[0.12em] text-slate-600">
          <span>Secure operations console</span>
          <span className="mono">v2.0</span>
        </div>
      </section>

      <section className="flex items-center justify-center px-5 py-12 sm:px-10">
        <div className="w-full max-w-[380px] animate-fade-up">
          <div className="mb-8 flex items-center gap-2.5 lg:hidden">
            <span className="relative flex h-9 w-9 items-center justify-center rounded-[10px] bg-slate-950 text-white">
              <ShieldCheck className="h-[18px] w-[18px]" />
              <span className="absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full border-2 border-white bg-emerald-400" />
            </span>
            <span className="text-sm font-semibold tracking-tight text-slate-950">
              Network Analyser
            </span>
          </div>

          <div className="mb-7">
            <div className="mb-4 flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">
              <span className="h-px w-5 bg-slate-300" />
              Operator access
            </div>
            <h2 className="text-[28px] font-semibold tracking-[-0.025em] text-slate-950">
              Sign in to your workspace
            </h2>
            <p className="mt-2 text-[13px] leading-relaxed text-slate-500">
              Use the credentials assigned to your operator account.
            </p>
          </div>

          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-2">
              <label
                htmlFor="username"
                className="text-[11px] font-semibold uppercase tracking-[0.1em] text-slate-600"
              >
                Username
              </label>
              <div className="relative">
                <UserRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <Input
                  id="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  autoComplete="username"
                  placeholder="e.g. admin"
                  className="h-10 pl-9"
                  required
                />
              </div>
            </div>
            <div className="space-y-2">
              <label
                htmlFor="password"
                className="text-[11px] font-semibold uppercase tracking-[0.1em] text-slate-600"
              >
                Password
              </label>
              <div className="relative">
                <KeyRound className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
                <Input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  placeholder="Enter your password"
                  className="h-10 px-9"
                  required
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((visible) => !visible)}
                  className="absolute right-2 top-1/2 flex h-7 w-7 -translate-y-1/2 items-center justify-center rounded-md text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
                  aria-label={showPassword ? 'Hide password' : 'Show password'}
                >
                  {showPassword ? (
                    <EyeOff className="h-4 w-4" />
                  ) : (
                    <Eye className="h-4 w-4" />
                  )}
                </button>
              </div>
            </div>

            {error !== null && (
              <p
                data-testid="login-error"
                role="alert"
                className="rounded-lg border border-rose-200 bg-rose-50 px-3 py-2 text-[12px] font-medium text-rose-700"
              >
                {error}
              </p>
            )}

            <Button
              type="submit"
              className="h-10 w-full"
              disabled={submitting}
            >
              {submitting ? 'Signing in…' : 'Sign in'}
            </Button>
          </form>

          <div className="mt-6 flex items-start gap-2.5 rounded-lg border border-slate-200 bg-slate-50 p-3">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" />
            <p className="text-[11px] leading-relaxed text-slate-500">
              Sessions are protected by short-lived access tokens. Initial
              passwords must be rotated before the console unlocks.
            </p>
          </div>
        </div>
      </section>
    </div>
  )
}
