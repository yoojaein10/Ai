"use client";

import React from "react";
import { CalendarEvent, EMOJI_MAP, VISIBILITY_OPTIONS } from "@/lib/types";
import { getTypeColor } from "@/lib/eventColors";

interface EventCardProps {
  event: CalendarEvent;
  onClick: (event: CalendarEvent) => void;
}

export default function EventCard({ event, onClick }: EventCardProps) {
  const formatTime = (dateStr: string) => {
    const d = new Date(dateStr);
    return d.toLocaleTimeString("ko-KR", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
  };

  const emojiDisplay = event.event_icon ? EMOJI_MAP[event.event_icon] || "" : "";
  const visOpt = VISIBILITY_OPTIONS.find((v) => v.value === event.visibility);

  return (
    <button
      onClick={() => onClick(event)}
      className="w-full flex items-center gap-3 p-3 rounded-xl bg-bg-primary border border-border hover:shadow-md transition-all duration-200 text-left group"
    >
      {/* Left color bar */}
      <div
        className="w-1 h-12 rounded-full flex-shrink-0"
        style={{ backgroundColor: getTypeColor(event.title)?.bg ?? (event.event_color || "#339AF0") }}
      />

      {/* Emoji */}
      {emojiDisplay && (
        <span className="text-xl flex-shrink-0">{emojiDisplay}</span>
      )}

      {/* Content */}
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium text-txt-primary truncate group-hover:text-accent transition-colors">
          {event.title}
        </p>
        <p className="text-xs text-txt-secondary mt-0.5">
          {event.is_all_day
            ? "종일"
            : `${formatTime(event.start_dt)} - ${formatTime(event.end_dt)}`}
        </p>
        {event.location && (
          <p className="text-xs text-txt-secondary mt-0.5 truncate">
            {event.location}
          </p>
        )}
      </div>

      {/* Visibility badge */}
      {visOpt && (
        <span
          className="text-xs px-2 py-0.5 rounded-full flex-shrink-0"
          style={{
            backgroundColor: `${visOpt.color}20`,
            color: visOpt.color,
          }}
        >
          {visOpt.label}
        </span>
      )}
    </button>
  );
}
