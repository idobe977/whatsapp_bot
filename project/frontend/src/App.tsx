import React from 'react';
import { ThemeProvider, createTheme, CssBaseline } from '@mui/material';
import { SurveyBuilder } from './components/SurveyBuilder';
import { SurveyList } from './components/SurveyList';
import { BotSettings } from './components/BotSettings';
import { Survey } from './types';
import rtlPlugin from 'stylis-plugin-rtl';
import { CacheProvider } from '@emotion/react';
import createCache from '@emotion/cache';
import { prefixer } from 'stylis';

// Create rtl cache
const cacheRtl = createCache({
  key: 'muirtl',
  stylisPlugins: [prefixer, rtlPlugin],
});

// Create rtl theme
const theme = createTheme({
  direction: 'rtl',
  typography: {
    fontFamily: 'Assistant, Roboto, sans-serif',
  },
  components: {
    MuiTextField: {
      defaultProps: {
        dir: 'rtl',
      },
    },
  },
});

const defaultBotSettings = {
  greenApi: {
    instance_id: '',
    api_token: '',
  },
  airtable: {
    api_key: '',
  },
  google: {
    credentials_file: '',
  },
  gemini: {
    api_key: '',
  },
  general: {
    log_level: 'INFO' as 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR',
    auto_retry_failed: true,
    max_retries: 3,
    retry_delay: 5,
  },
};

const App: React.FC = () => {
  const [view, setView] = React.useState<'list' | 'builder'>('list');
  const [surveys, setSurveys] = React.useState<Survey[]>([]);
  const [selectedSurvey, setSelectedSurvey] = React.useState<Survey | null>(null);
  const [botSettingsOpen, setBotSettingsOpen] = React.useState(false);
  const [botSettings, setBotSettings] = React.useState(defaultBotSettings);

  const handleSurveySelect = (survey: Survey) => {
    setSelectedSurvey(survey);
    setView('builder');
  };

  const handleSurveyDelete = (surveyToDelete: Survey) => {
    setSurveys(surveys.filter(s => s.name !== surveyToDelete.name));
  };

  const handleSurveyDuplicate = (surveyToDuplicate: Survey) => {
    const newSurvey = {
      ...surveyToDuplicate,
      name: `${surveyToDuplicate.name} (העתק)`,
    };
    setSurveys([...surveys, newSurvey]);
  };

  const handleSurveyCreate = () => {
    const newSurvey: Survey = {
      name: 'שאלון חדש',
      trigger_phrases: [],
      airtable: {
        base_id: '',
        table_id: '',
        fieldMappings: []
      },
      questions: [],
      messages: {
        welcome: 'ברוכים הבאים לשאלון!',
        completion: {
          text: 'תודה על מילוי השאלון!',
          should_generate_summary: false,
        },
        error: 'מצטערים, אירעה שגיאה. אנא נסו שוב מאוחר יותר.',
      },
      ai_prompts: {
        reflections: {
          empathetic: {
            prompt: '',
          },
          professional: {
            prompt: '',
          },
        },
        summary: {
          prompt: '',
          include_recommendations: true,
          max_length: 500,
        },
      },
    };
    setSurveys([...surveys, newSurvey]);
    setSelectedSurvey(newSurvey);
    setView('builder');
  };

  return (
    <CacheProvider value={cacheRtl}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        {view === 'list' ? (
          <SurveyList
            surveys={surveys}
            onSurveySelect={handleSurveySelect}
            onSurveyDelete={handleSurveyDelete}
            onSurveyDuplicate={handleSurveyDuplicate}
            onSurveyCreate={handleSurveyCreate}
          />
        ) : (
          selectedSurvey && (
            <SurveyBuilder
              survey={selectedSurvey}
              onBack={() => setView('list')}
              onSettingsClick={() => setBotSettingsOpen(true)}
            />
          )
        )}

        <BotSettings
          open={botSettingsOpen}
          onClose={() => setBotSettingsOpen(false)}
          settings={botSettings}
          onSave={setBotSettings}
        />
      </ThemeProvider>
    </CacheProvider>
  );
};

export default App; 