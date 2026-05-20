export default function Logo({ size = 'md' }) {
  const dims = size === 'lg' ? { w: 64, h: 64, text: 'text-3xl' } : { w: 36, h: 36, text: 'text-lg' }
  return (
    <div className="flex items-center gap-3">
      <svg width={dims.w} height={dims.h} viewBox="0 0 64 64" fill="none">
        {/* Refined monogram: A overlaid on subtle frame */}
        <rect x="1" y="1" width="62" height="62" rx="6" stroke="#C5A572" strokeWidth="1"/>
        <path
          d="M22 46 L32 18 L42 46 M26 38 L38 38"
          stroke="#C5A572"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
          fill="none"
        />
        <circle cx="32" cy="14" r="1.5" fill="#C5A572"/>
      </svg>
      <div className="flex flex-col leading-none">
        <span className={`font-display ${dims.text} text-cream-50 tracking-tightest`}>Ascot</span>
        <span className="font-sans text-[0.65rem] text-cream-300 uppercase tracking-[0.2em] mt-0.5">
          Wealth Management
        </span>
      </div>
    </div>
  )
}
