import { useEffect, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Film, Save, Sliders } from 'lucide-react'
import { config } from '@/api/endpoints'
import { PageHeader } from '@/components/ui/PageHeader'
import { PageContainer } from '@/components/ui/PageContainer'
import { Button } from '@/components/ui/Button'
import { useToast } from '@/components/ui/Toast'
import type { AppConfig } from '@/types/api'
import { cn } from '@/lib/utils'

const ENCODERS = ['vaapi', 'hevc_qsv', 'h264_qsv', 'libx265', 'libx264', 'av1_qsv']
const PRESETS = ['veryfast', 'fast', 'medium', 'slow', 'slower', 'veryslow']
const AUDIO_CODECS = ['aac', 'libopus', 'copy']

// Shape of the `advanced_encode` block as returned by the backend.
// Each toggle has an `enabled` flag plus its own payload — the backend
// only honors fields whose `enabled` is true.
interface AdvancedEncode {
  bitrate:       { enabled: boolean; max: string; min: string; avg: string; bufsize: string }
  tune:          { enabled: boolean; value: string }
  profile:       { enabled: boolean; value: string }
  level:         { enabled: boolean; value: string }
  tier:          { enabled: boolean; value: string }
  pixel_format:  { enabled: boolean; value: string }
  gop:           { enabled: boolean; keyint: number }
  x265_params:   { enabled: boolean; value: string }
  audio:         { enabled: boolean; codec: string; bitrate: string }
  video_filters: { enabled: boolean; value: string }
}

const ADVANCED_DEFAULT: AdvancedEncode = {
  bitrate:       { enabled: false, max: '', min: '', avg: '', bufsize: '' },
  tune:          { enabled: false, value: 'animation' },
  profile:       { enabled: false, value: 'main' },
  level:         { enabled: false, value: '' },
  tier:          { enabled: false, value: 'main' },
  pixel_format:  { enabled: false, value: 'yuv420p' },
  gop:           { enabled: false, keyint: 250 },
  x265_params:   { enabled: false, value: '' },
  audio:         { enabled: false, codec: 'aac', bitrate: '192k' },
  video_filters: { enabled: false, value: '' },
}

export function EncodingSettingsPage() {
  const toast = useToast()
  const qc = useQueryClient()
  const cfgQ = useQuery({ queryKey: ['config'], queryFn: config.get })

  const [encoder, setEncoder] = useState<string>('vaapi')
  const [preset, setPreset] = useState<string>('medium')
  const [crf, setCrf] = useState<number>(26)
  const [advanced, setAdvanced] = useState<AdvancedEncode>(ADVANCED_DEFAULT)
  const [showAdvanced, setShowAdvanced] = useState(false)

  useEffect(() => {
    if (cfgQ.data) {
      setEncoder((cfgQ.data.encoder as string) ?? 'vaapi')
      setPreset((cfgQ.data.preset as string) ?? 'medium')
      setCrf((cfgQ.data.crf as number) ?? 26)
      const adv = (cfgQ.data as { advanced_encode?: Partial<AdvancedEncode> }).advanced_encode
      if (adv) {
        setAdvanced({ ...ADVANCED_DEFAULT, ...adv } as AdvancedEncode)
        // Auto-expand the section if any toggle is already on so the user
        // doesn't have to hunt for it.
        if (Object.values(adv).some((v) => v && (v as { enabled?: boolean }).enabled)) {
          setShowAdvanced(true)
        }
      }
    }
  }, [cfgQ.data])

  const saveMut = useMutation({
    mutationFn: () =>
      config.update({
        encoder,
        preset,
        crf,
        advanced_encode: advanced,
      } as Partial<AppConfig>),
    onSuccess: () => {
      toast.push('Encoding settings saved', 'success')
      qc.invalidateQueries({ queryKey: ['config'] })
    },
    onError: (e: Error) => toast.push(e.message, 'error'),
  })

  const ensureEncoderInList = ENCODERS.includes(encoder) ? ENCODERS : [encoder, ...ENCODERS]
  const ensurePresetInList = PRESETS.includes(preset) ? PRESETS : [preset, ...PRESETS]

  return (
    <PageContainer>
      <PageHeader icon={Film} title="Encoding settings" description="Encoder, preset and per-codec advanced options." />

      <section className="card p-5 grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div className="space-y-2">
          <label className="label">Encoder</label>
          <select value={encoder} onChange={(e) => setEncoder(e.target.value)} className="input">
            {ensureEncoderInList.map((x) => <option key={x} value={x}>{x}</option>)}
          </select>
        </div>
        <div className="space-y-2">
          <label className="label">Preset</label>
          <select value={preset} onChange={(e) => setPreset(e.target.value)} className="input">
            {ensurePresetInList.map((x) => <option key={x} value={x}>{x}</option>)}
          </select>
        </div>
        <div className="space-y-2">
          <label className="label">CRF / quality</label>
          <input
            type="number"
            min={0}
            max={51}
            value={crf}
            onChange={(e) => setCrf(parseInt(e.target.value, 10) || 26)}
            className="input"
          />
          <p className="text-xs text-fg-muted">Lower = higher quality. Typical: 22–28 for HEVC.</p>
        </div>
      </section>

      {/* Advanced encode — collapsed by default, expanded if any toggle is on. */}
      <section className="card overflow-hidden">
        <button
          type="button"
          onClick={() => setShowAdvanced((v) => !v)}
          className="w-full px-5 py-4 flex items-center gap-3 text-left hover:bg-bg-subtle/50 transition"
          aria-expanded={showAdvanced}
        >
          <div className="h-9 w-9 rounded-lg bg-accent/10 text-accent flex items-center justify-center shrink-0">
            <Sliders size={16} />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-sm font-semibold">Advanced encode options</div>
            <div className="text-xs text-fg-muted">
              Bitrate caps, tune, profile, pixel format, GOP, x265 params, audio overrides, filters.
            </div>
          </div>
          <ChevronDown
            size={18}
            className={cn('text-fg-muted shrink-0 transition-transform duration-200', showAdvanced && 'rotate-180')}
          />
        </button>
        {showAdvanced && (
          <div className="border-t border-border p-5 space-y-4">
            {/* Bitrate */}
            <AdvancedToggle
              label="Bitrate caps"
              hint="Override CRF with explicit max/min/avg bitrate (kbps) and VBV bufsize."
              enabled={advanced.bitrate.enabled}
              onToggle={(e) => setAdvanced((a) => ({ ...a, bitrate: { ...a.bitrate, enabled: e } }))}
            >
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {(['max', 'min', 'avg', 'bufsize'] as const).map((k) => (
                  <div key={k} className="space-y-1">
                    <label className="label">{k}</label>
                    <input
                      value={advanced.bitrate[k]}
                      disabled={!advanced.bitrate.enabled}
                      onChange={(ev) =>
                        setAdvanced((a) => ({ ...a, bitrate: { ...a.bitrate, [k]: ev.target.value } }))
                      }
                      className="input"
                    />
                  </div>
                ))}
              </div>
            </AdvancedToggle>

            <AdvancedToggle
              label="Tune"
              hint="ffmpeg --tune flag (e.g. animation, film, grain)."
              enabled={advanced.tune.enabled}
              onToggle={(e) => setAdvanced((a) => ({ ...a, tune: { ...a.tune, enabled: e } }))}
            >
              <input
                value={advanced.tune.value}
                disabled={!advanced.tune.enabled}
                onChange={(ev) => setAdvanced((a) => ({ ...a, tune: { ...a.tune, value: ev.target.value } }))}
                className="input"
              />
            </AdvancedToggle>

            <AdvancedToggle
              label="Profile"
              hint="Codec profile (main, main10, high, ...)."
              enabled={advanced.profile.enabled}
              onToggle={(e) => setAdvanced((a) => ({ ...a, profile: { ...a.profile, enabled: e } }))}
            >
              <input
                value={advanced.profile.value}
                disabled={!advanced.profile.enabled}
                onChange={(ev) => setAdvanced((a) => ({ ...a, profile: { ...a.profile, value: ev.target.value } }))}
                className="input"
              />
            </AdvancedToggle>

            <AdvancedToggle
              label="Level"
              hint="Codec level cap (e.g. 4.1, 5.1)."
              enabled={advanced.level.enabled}
              onToggle={(e) => setAdvanced((a) => ({ ...a, level: { ...a.level, enabled: e } }))}
            >
              <input
                value={advanced.level.value}
                disabled={!advanced.level.enabled}
                onChange={(ev) => setAdvanced((a) => ({ ...a, level: { ...a.level, value: ev.target.value } }))}
                className="input"
              />
            </AdvancedToggle>

            <AdvancedToggle
              label="Tier"
              hint="HEVC tier (main, high)."
              enabled={advanced.tier.enabled}
              onToggle={(e) => setAdvanced((a) => ({ ...a, tier: { ...a.tier, enabled: e } }))}
            >
              <input
                value={advanced.tier.value}
                disabled={!advanced.tier.enabled}
                onChange={(ev) => setAdvanced((a) => ({ ...a, tier: { ...a.tier, value: ev.target.value } }))}
                className="input"
              />
            </AdvancedToggle>

            <AdvancedToggle
              label="Pixel format"
              hint="e.g. yuv420p, yuv420p10le for 10-bit."
              enabled={advanced.pixel_format.enabled}
              onToggle={(e) => setAdvanced((a) => ({ ...a, pixel_format: { ...a.pixel_format, enabled: e } }))}
            >
              <input
                value={advanced.pixel_format.value}
                disabled={!advanced.pixel_format.enabled}
                onChange={(ev) => setAdvanced((a) => ({ ...a, pixel_format: { ...a.pixel_format, value: ev.target.value } }))}
                className="input"
              />
            </AdvancedToggle>

            <AdvancedToggle
              label="GOP / keyint"
              hint="Keyframe interval (frames between IDR keyframes)."
              enabled={advanced.gop.enabled}
              onToggle={(e) => setAdvanced((a) => ({ ...a, gop: { ...a.gop, enabled: e } }))}
            >
              <input
                type="number"
                value={advanced.gop.keyint}
                disabled={!advanced.gop.enabled}
                onChange={(ev) => setAdvanced((a) => ({ ...a, gop: { ...a.gop, keyint: parseInt(ev.target.value, 10) || 0 } }))}
                className="input"
              />
            </AdvancedToggle>

            <AdvancedToggle
              label="x265 params"
              hint="Colon-separated key=value pairs passed to x265 directly."
              enabled={advanced.x265_params.enabled}
              onToggle={(e) => setAdvanced((a) => ({ ...a, x265_params: { ...a.x265_params, enabled: e } }))}
            >
              <input
                value={advanced.x265_params.value}
                disabled={!advanced.x265_params.enabled}
                onChange={(ev) => setAdvanced((a) => ({ ...a, x265_params: { ...a.x265_params, value: ev.target.value } }))}
                placeholder="aq-mode=3:rd=4:no-sao=1"
                className="input"
              />
            </AdvancedToggle>

            <AdvancedToggle
              label="Audio override"
              hint="Override the per-stream audio defaults (codec + bitrate)."
              enabled={advanced.audio.enabled}
              onToggle={(e) => setAdvanced((a) => ({ ...a, audio: { ...a.audio, enabled: e } }))}
            >
              <div className="grid grid-cols-2 gap-2">
                <div className="space-y-1">
                  <label className="label">codec</label>
                  <select
                    value={advanced.audio.codec}
                    disabled={!advanced.audio.enabled}
                    onChange={(ev) => setAdvanced((a) => ({ ...a, audio: { ...a.audio, codec: ev.target.value } }))}
                    className="input"
                  >
                    {AUDIO_CODECS.map((x) => <option key={x} value={x}>{x}</option>)}
                  </select>
                </div>
                <div className="space-y-1">
                  <label className="label">bitrate</label>
                  <input
                    value={advanced.audio.bitrate}
                    disabled={!advanced.audio.enabled}
                    onChange={(ev) => setAdvanced((a) => ({ ...a, audio: { ...a.audio, bitrate: ev.target.value } }))}
                    className="input"
                  />
                </div>
              </div>
            </AdvancedToggle>

            <AdvancedToggle
              label="Video filters"
              hint="ffmpeg -vf chain. E.g. scale=1920:-2,format=yuv420p"
              enabled={advanced.video_filters.enabled}
              onToggle={(e) => setAdvanced((a) => ({ ...a, video_filters: { ...a.video_filters, enabled: e } }))}
            >
              <input
                value={advanced.video_filters.value}
                disabled={!advanced.video_filters.enabled}
                onChange={(ev) => setAdvanced((a) => ({ ...a, video_filters: { ...a.video_filters, value: ev.target.value } }))}
                className="input"
              />
            </AdvancedToggle>
          </div>
        )}
      </section>

      <div className="flex justify-end">
        <Button onClick={() => saveMut.mutate()} disabled={saveMut.isPending}>
          <Save size={14} /> {saveMut.isPending ? 'Saving…' : 'Save changes'}
        </Button>
      </div>
    </PageContainer>
  )
}

function AdvancedToggle({
  label, hint, enabled, onToggle, children,
}: {
  label: string
  hint?: string
  enabled: boolean
  onToggle: (v: boolean) => void
  children: React.ReactNode
}) {
  return (
    <div className={cn('rounded-lg border p-4', enabled ? 'border-accent/40 bg-accent/5' : 'border-border')}>
      <div className="flex items-start gap-3 mb-3">
        <button
          type="button"
          role="switch"
          aria-checked={enabled}
          onClick={() => onToggle(!enabled)}
          className={cn(
            'mt-0.5 inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border transition-colors',
            enabled ? 'bg-accent border-accent' : 'bg-bg-subtle border-border',
          )}
        >
          <span
            className={cn(
              'inline-block h-4 w-4 transform rounded-full bg-white transition-transform',
              enabled ? 'translate-x-4' : 'translate-x-0.5',
            )}
          />
        </button>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium">{label}</div>
          {hint && <div className="text-xs text-fg-muted mt-0.5">{hint}</div>}
        </div>
      </div>
      <div className={cn(!enabled && 'opacity-50 pointer-events-none')}>{children}</div>
    </div>
  )
}
