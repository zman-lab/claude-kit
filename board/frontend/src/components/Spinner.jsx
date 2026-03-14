export default function Spinner({ size = 'md', className = '' }) {
  const sizes = { sm: 'w-4 h-4', md: 'w-8 h-8', lg: 'w-12 h-12' }
  return (
    <div className={`flex justify-center items-center py-8 ${className}`}>
      <div className={`${sizes[size]} border-2 border-slate-300 dark:border-slate-600 border-t-blue-500 rounded-full animate-spin`} />
    </div>
  )
}
