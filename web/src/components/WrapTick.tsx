// category axis tick that wraps long labels (channel names) instead of letting Recharts drop every other one
export function WrapTick({ x, y, payload }: { x?: number; y?: number; payload?: { value: string } }) {
  const lines: string[] = []
  for (const word of String(payload?.value ?? '').split(' ')) {
    const last = lines.at(-1)
    if (last && (last + ' ' + word).length <= 12) lines[lines.length - 1] = `${last} ${word}`
    else lines.push(word)
  }
  return (
    <text x={x} y={y} textAnchor="middle" className="fill-muted-foreground text-[10px] sm:text-xs">
      {lines.map((line, i) => (
        <tspan key={i} x={x} dy={i === 0 ? '0.9em' : '1.1em'}>
          {line}
        </tspan>
      ))}
    </text>
  )
}
