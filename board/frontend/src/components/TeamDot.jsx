export default function TeamDot({ team, size = 8 }) {
  if (!team) return null
  return (
    <span
      className="inline-block rounded-full shrink-0"
      style={{
        width: size,
        height: size,
        backgroundColor: `var(--team-${team}, #94a3b8)`,
      }}
    />
  )
}
