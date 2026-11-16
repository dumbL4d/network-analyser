import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { RANGE_OPTIONS } from '@/lib/history'
import type { HistoryRange } from '@/types/device'

/**
 * Time-range selector shared by the device detail chart and the Metrics view.
 * 'Live' is the recent in-memory samples; the other ranges come from the
 * database at a resolution the backend chooses.
 */
export default function TimeRangeSelect({
  value,
  onChange,
}: {
  value: HistoryRange
  onChange: (range: HistoryRange) => void
}) {
  return (
    <Select
      value={value}
      onValueChange={(next) => onChange(next as HistoryRange)}
    >
      <SelectTrigger
        data-testid="time-range"
        aria-label="Time range"
        className="h-8 w-[150px] text-xs"
      >
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {RANGE_OPTIONS.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}
