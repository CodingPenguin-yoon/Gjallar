import { operationStatusLabel, operationStatusTone } from '../model'

export default function OperationStatusBadge({ status }) {
  return (
    <span className={`inline-flex rounded-full border px-2.5 py-1 text-xs font-semibold ${operationStatusTone(status)}`}>
      {operationStatusLabel(status)}
    </span>
  )
}
