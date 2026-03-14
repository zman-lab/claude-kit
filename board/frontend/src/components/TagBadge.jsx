export default function TagBadge({ tag, className = '' }) {
  if (!tag) return null
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-medium tag-${tag} ${className}`}>
      {tag}
    </span>
  )
}
