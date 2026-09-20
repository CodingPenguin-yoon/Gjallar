"""Independent current/history observations without persistence or scheduling."""
from app.monitoring.domain import MonitoringError, TIMEFRAMES, current_metrics, descriptors, history_metrics, now_utc
from app.monitoring.thresholds import threshold_report


class MonitoringService:
    def __init__(self, client, clock=now_utc):
        self.client, self.clock = client, clock

    def query(self, target, timeframe='hour'):
        if timeframe not in TIMEFRAMES:
            raise MonitoringError('MONITORING_TIMEFRAME_INVALID', '지원 기간을 선택하세요.', 422)
        result = {'target': target.to_dict(), 'timeframe': timeframe, 'supported_timeframes': list(TIMEFRAMES),
                  'metrics': descriptors(target.kind), 'read_only': True}
        for section in ('current', 'history'):
            try:
                raw = self.client.current(target) if section == 'current' else self.client.history(target, timeframe)
                now = self.clock()
                result[section] = (current_metrics(target.kind, raw, received_at=now.isoformat()) if section == 'current'
                                   else history_metrics(target.kind, raw, received_at=now.isoformat(), now=now.timestamp()))
            except MonitoringError as exc:
                if exc.status_code in {403, 422}: raise
                result[section] = {'available': False, 'code': exc.code, 'message': exc.message,
                                   'received_at': self.clock().isoformat()}
        result['partial'] = not all(result[section]['available'] for section in ('current', 'history'))
        result['thresholds'] = threshold_report(target, result['current'], result['history'])
        return result
