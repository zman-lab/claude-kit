export default function Empty({ message = '데이터가 없습니다', icon = '📭' }) {
  return (
    <div className="flex flex-col items-center justify-center py-16 text-slate-400 dark:text-slate-500">
      <span className="text-4xl mb-3">{icon}</span>
      <p className="text-sm">{message}</p>
    </div>
  )
}
