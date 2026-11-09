import { useId } from 'react'

// the Gemini star in its own colors; marks every action or text that comes from the LLM
export function GeminiIcon({ className = 'size-4' }: { className?: string }) {
  const gradient = useId()
  return (
    <svg aria-hidden viewBox="0 0 24 24" className={className} fill={`url(#${gradient})`}>
      <defs>
        <linearGradient id={gradient} x1="3" y1="20" x2="21" y2="4" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#4285F4" />
          <stop offset="0.55" stopColor="#9B72CB" />
          <stop offset="1" stopColor="#D96570" />
        </linearGradient>
      </defs>
      <path d="M12 24A14.304 14.304 0 0 0 0 12 14.304 14.304 0 0 0 12 0a14.305 14.305 0 0 0 12 12 14.305 14.305 0 0 0-12 12" />
    </svg>
  )
}
