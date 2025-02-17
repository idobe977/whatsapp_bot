export interface Question {
  id: string;
  type: 'text' | 'poll' | 'voice' | 'meeting_scheduler';
  text: string;
  options?: string[];
  reflection?: {
    type: 'empathetic' | 'professional';
    enabled: boolean;
  };
  flow?: {
    if?: {
      answer: string;
      then: {
        say?: string;
        goto?: string;
      };
    };
    else_if?: Array<{
      answer: string;
      then: {
        say?: string;
        goto?: string;
      };
    }>;
  };
}

export interface CalendarSettings {
  working_hours: {
    [key: string]: {
      start: string;
      end: string;
    };
  };
  meeting_duration: number;
  buffer_between_meetings: number;
  days_to_show: number;
  timezone: string;
  calendar_id: string;
  meeting_title_template: string;
  meeting_description_template: string;
}

export interface Survey {
  name: string;
  trigger_phrases: string[];
  airtable: {
    base_id: string;
    table_id: string;
    fieldMappings: Array<{
      questionId: string;
      airtableField: string;
    }>;
  };
  calendar_settings?: CalendarSettings;
  questions: Question[];
  messages: {
    welcome: string;
    completion: {
      text: string;
      should_generate_summary: boolean;
    };
    error: string;
  };
  ai_prompts: {
    reflections: {
      empathetic: {
        prompt: string;
      };
      professional: {
        prompt: string;
      };
    };
    summary: {
      prompt: string;
      include_recommendations: boolean;
      max_length: number;
    };
  };
}

export interface NodeData {
  id: string;
  type: string;
  data: Question;
  position: { x: number; y: number };
} 