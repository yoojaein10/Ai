import { Modal, Descriptions, Tag, Button, Space, Popconfirm } from "antd";
import {
  useEvent,
  useDeleteEvent,
  useRespondParticipant,
  type ParticipantResponseValue,
} from "../../api/calendar";
import { useCalendarFilterStore } from "../../store/calendarFilterStore";
import { resolveEventColor } from "../../utils/eventColor";

const EVENT_TYPE_LABEL: Record<string, string> = {
  LEAVE: "휴가",
  TRAVEL: "출장",
  MEETING: "회의",
  MANUAL: "일반",
  OTHER: "기타",
};

const RESPONSE_LABEL: Record<ParticipantResponseValue, string> = {
  PENDING: "대기",
  ACCEPTED: "수락",
  DECLINED: "거절",
  TENTATIVE: "미정",
};

function formatDt(s: string | null | undefined): string {
  if (!s) return "-";
  return s.replace("T", " ").slice(0, 16);
}

export function EventDetailModal() {
  const eventId = useCalendarFilterStore((s) => s.selectedEventId);
  const setSelectedEventId = useCalendarFilterStore(
    (s) => s.setSelectedEventId,
  );
  const { data: event, isLoading } = useEvent(eventId);
  const delMut = useDeleteEvent();
  const respondMut = useRespondParticipant();

  const close = () => setSelectedEventId(null);

  const handleDelete = async () => {
    if (!eventId) return;
    await delMut.mutateAsync(eventId);
    close();
  };

  const handleRespond = async (response: ParticipantResponseValue) => {
    if (!eventId) return;
    await respondMut.mutateAsync({ eventId, response });
  };

  return (
    <Modal
      open={eventId !== null}
      title={event?.title ?? "이벤트"}
      onCancel={close}
      width={640}
      footer={
        <Space>
          {event && (
            <>
              <Button onClick={() => handleRespond("ACCEPTED")}>수락</Button>
              <Button onClick={() => handleRespond("TENTATIVE")}>미정</Button>
              <Button onClick={() => handleRespond("DECLINED")}>거절</Button>
              <Popconfirm
                title="이벤트를 삭제하시겠습니까?"
                onConfirm={handleDelete}
              >
                <Button danger>삭제</Button>
              </Popconfirm>
            </>
          )}
          <Button type="primary" onClick={close}>
            닫기
          </Button>
        </Space>
      }
    >
      {isLoading && <p>불러오는 중…</p>}
      {event && (
        <Descriptions
          bordered
          size="small"
          column={1}
          labelStyle={{ width: 120 }}
        >
          <Descriptions.Item label="캘린더">
            <Tag
              color={resolveEventColor(
                event.event_type,
                event.calendar_color,
              )}
            >
              {event.calendar_name ?? "-"}
            </Tag>
          </Descriptions.Item>
          <Descriptions.Item label="구분">
            {EVENT_TYPE_LABEL[event.event_type] ?? event.event_type}
          </Descriptions.Item>
          <Descriptions.Item label="시작">
            {formatDt(event.start_at)}
          </Descriptions.Item>
          <Descriptions.Item label="종료">
            {formatDt(event.end_at)}
          </Descriptions.Item>
          <Descriptions.Item label="종일">
            {event.all_day ? "예" : "아니오"}
          </Descriptions.Item>
          <Descriptions.Item label="주최자">
            {event.owner_name ?? "-"}
          </Descriptions.Item>
          <Descriptions.Item label="장소">
            {event.location ?? "-"}
          </Descriptions.Item>
          <Descriptions.Item label="공개 범위">
            {event.visibility}
          </Descriptions.Item>
          <Descriptions.Item label="설명">
            {event.description ?? "-"}
          </Descriptions.Item>
          <Descriptions.Item label="참석자">
            {event.participants.length === 0 ? (
              "-"
            ) : (
              <Space wrap size={[4, 4]}>
                {event.participants.map((p) => (
                  <Tag key={p.id}>
                    {p.emp_name ?? `#${p.emp_id}`}
                    {" · "}
                    {RESPONSE_LABEL[p.response]}
                  </Tag>
                ))}
              </Space>
            )}
          </Descriptions.Item>
          {event.source_type === "APPROVAL_DOC" && (
            <Descriptions.Item label="연동">
              전자결재 문서 #{event.source_ref}
            </Descriptions.Item>
          )}
        </Descriptions>
      )}
    </Modal>
  );
}
