import { useParams } from 'react-router-dom'

export default function DeviceDetailView() {
  const { deviceId } = useParams<{ deviceId: string }>()

  return (
    <div className="p-8">
      <p className="text-sm text-muted-foreground">
        Device Detail for {deviceId} — coming in Ticket 2.4
      </p>
    </div>
  )
}
