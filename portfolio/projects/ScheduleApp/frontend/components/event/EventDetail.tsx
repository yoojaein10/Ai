"use client";

import React from "react";
import { CalendarEvent, EMOJI_MAP, VISIBILITY_OPTIONS } from "@/lib/types";
import { getTypeColor } from "@/lib/eventColors";
import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";
import AttendeeList from "./AttendeeList";

interface EventDetailProps {
  event: CalendarEvent | null;
  isOpen: boolean;
  onClose: () => void;
  onEdit: (event: CalendarEvent) => void;
  onDelete: (eventId: number) => void;
  currentEmpno?: number;
}

export default function EventDetail({
  event,
  isOpen,
  onClose,
  onEdit,
  onDelete,
  currentEmpno,
}: EventDetailProps) {
  if (!event) return null;

  const formatDateTime = (dateStr: string) => {
    const d = new Date(dateStr);
    return d.toLocaleString("ko-KR", {
      year: "numeric",
      month: "long",
      day: "numeric",
      weekday: "short",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  };

  const emojiDisplay = event.event_icon ? EMOJI_MAP[event.event_icon] || "" : "";
  const visOpt = VISIBILITY_OPTIONS.find((v) => v.value === event.visibility);
  const isOwner = currentEmpno === event.creator_id;

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="일정 상세">
      <div className="space-y-4">
        {/* Title with color bar and emoji */}
        <div className="flex items-start gap-3">
          <div
            className="w-1.5 h-full min-h-[40px] rounded-full flex-shrink-0 mt-1"
            style={{ backgroundColor: getTypeColor(event.title)?.bg ?? (event.event_color || "#339AF0") }}
          />
          <div>
            <div className="flex items-center gap-2">
              {emojiDisplay && (
                <span className="text-2xl">{emojiDisplay}</span>
              )}
              <h3 className="text-xl font-bold text-txt-primary">
                {event.title}
              </h3>
            </div>
            <div className="flex items-center gap-2 mt-1">
              {visOpt && (
                <span
                  className="inline-block text-xs px-2 py-0.5 rounded-full"
                  style={{
                    backgroundColor: `${visOpt.color}20`,
                    color: visOpt.color,
                  }}
                >
                  {visOpt.label}
                </span>
              )}
              {event.creator_name && (
                <span className="text-xs text-txt-secondary">
                  작성자: {event.creator_name}
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Time */}
        <div className="flex items-start gap-3 text-sm">
          <svg className="w-5 h-5 text-txt-secondary flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <div>
            <p className="text-txt-primary">
              {event.is_all_day ? "종일" : formatDateTime(event.start_dt)}
            </p>
            {!event.is_all_day && (
              <p className="text-txt-secondary">
                ~ {formatDateTime(event.end_dt)}
              </p>
            )}
          </div>
        </div>

        {/* Location */}
        {event.location && (
          <div className="flex items-start gap-3 text-sm">
            <svg className="w-5 h-5 text-txt-secondary flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" />
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
            </svg>
            <p className="text-txt-primary">{event.location}</p>
          </div>
        )}

        {/* Description */}
        {event.description && (
          <div className="flex items-start gap-3 text-sm">
            <svg className="w-5 h-5 text-txt-secondary flex-shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h7" />
            </svg>
            <p className="text-txt-primary whitespace-pre-wrap">
              {event.description}
            </p>
          </div>
        )}

        {/* Attendees */}
        {event.attendees && event.attendees.length > 0 && (
          <div className="pt-2">
            <AttendeeList
              attendees={event.attendees}
              onChange={() => {}}
              editable={false}
            />
          </div>
        )}

        {/* Actions - only show edit/delete for owner */}
        {isOwner && (
          <div className="flex gap-3 pt-4 border-t border-border">
            <Button
              variant="secondary"
              onClick={() => onEdit(event)}
              className="flex-1"
            >
              수정
            </Button>
            <Button
              variant="danger"
              onClick={() => {
                if (window.confirm("이 일정을 삭제하시겠습니까?")) {
                  onDelete(event.event_id);
                }
              }}
              className="flex-1"
            >
              삭제
            </Button>
          </div>
        )}
      </div>
    </Modal>
  );
}
