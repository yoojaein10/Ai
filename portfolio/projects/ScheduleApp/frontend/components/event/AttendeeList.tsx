"use client";

import React, { useState, useCallback } from "react";
import { EventAttendee, User, ApiResponse } from "@/lib/types";
import api from "@/lib/api";
import Input from "@/components/ui/Input";

interface AttendeeListProps {
  attendees: EventAttendee[];
  onChange: (attendees: EventAttendee[]) => void;
  editable?: boolean;
}

export default function AttendeeList({
  attendees,
  onChange,
  editable = true,
}: AttendeeListProps) {
  const [searchQuery, setSearchQuery] = useState("");
  const [searchResults, setSearchResults] = useState<User[]>([]);
  const [searching, setSearching] = useState(false);

  const searchUsers = useCallback(async (query: string) => {
    if (query.length < 2) {
      setSearchResults([]);
      return;
    }
    setSearching(true);
    try {
      const { data } = await api.get<ApiResponse<User[]>>("/users/search", {
        params: { q: query },
      });
      const list = data.data ?? data;
      setSearchResults(Array.isArray(list) ? list : []);
    } catch {
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  }, []);

  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const value = e.target.value;
    setSearchQuery(value);
    searchUsers(value);
  };

  const addAttendee = (user: User) => {
    if (attendees.some((a) => a.apwid === user.apwid)) return;
    const newAttendee: EventAttendee = {
      apwid: user.apwid,
      name: user.name,
      status: "pending",
    };
    onChange([...attendees, newAttendee]);
    setSearchQuery("");
    setSearchResults([]);
  };

  const removeAttendee = (apwid: number) => {
    onChange(attendees.filter((a) => a.apwid !== apwid));
  };

  return (
    <div>
      <label className="block text-sm font-medium text-txt-primary mb-2">
        참석자
      </label>

      {/* Attendee list */}
      {attendees.length > 0 && (
        <div className="space-y-1.5 mb-3">
          {attendees.map((att) => (
            <div
              key={att.apwid}
              className="flex items-center justify-between px-3 py-2 bg-bg-secondary rounded-lg"
            >
              <div className="flex items-center gap-2">
                <div className="w-7 h-7 rounded-full bg-accent/20 flex items-center justify-center text-xs font-medium text-accent">
                  {att.name.charAt(0)}
                </div>
                <span className="text-sm text-txt-primary">{att.name}</span>
              </div>
              <div className="flex items-center gap-2">
                {editable && (
                  <button
                    type="button"
                    onClick={() => removeAttendee(att.apwid)}
                    className="p-1 rounded-full hover:bg-bg-secondary transition-colors"
                  >
                    <svg className="w-4 h-4 text-txt-secondary" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Search input */}
      {editable && (
        <div className="relative">
          <Input
            placeholder="사용자 검색..."
            value={searchQuery}
            onChange={handleSearchChange}
          />
          {/* Search results dropdown */}
          {searchResults.length > 0 && (
            <div className="absolute top-full left-0 right-0 mt-1 bg-bg-primary border border-border rounded-lg shadow-lg z-10 max-h-40 overflow-y-auto">
              {searchResults.map((user) => {
                const alreadyAdded = attendees.some((a) => a.apwid === user.apwid);
                return (
                  <button
                    key={user.apwid}
                    type="button"
                    onClick={() => addAttendee(user)}
                    disabled={alreadyAdded}
                    className={`w-full text-left px-3 py-2 text-sm hover:bg-bg-secondary transition-colors ${
                      alreadyAdded ? "opacity-50 cursor-not-allowed" : ""
                    }`}
                  >
                    <span className="font-medium">{user.name}</span>
                    <span className="text-txt-secondary ml-2">
                      {user.team_name || ""}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
          {searching && (
            <div className="absolute top-full left-0 right-0 mt-1 bg-bg-primary border border-border rounded-lg shadow-lg z-10 px-3 py-4 text-center text-sm text-txt-secondary">
              검색 중...
            </div>
          )}
        </div>
      )}
    </div>
  );
}
