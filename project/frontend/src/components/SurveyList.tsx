import React from 'react';
import {
  Box,
  List,
  ListItem,
  ListItemText,
  ListItemSecondaryAction,
  IconButton,
  Typography,
  TextField,
  InputAdornment,
  Paper,
  Button,
  Menu,
  MenuItem,
  Chip,
  Dialog,
  DialogTitle,
  DialogContent,
  DialogContentText,
  DialogActions
} from '@mui/material';
import {
  Search,
  Add,
  MoreVert,
  Edit,
  Delete,
  ContentCopy,
  Download,
  Upload
} from '@mui/icons-material';
import { Survey } from '../types';

interface SurveyListProps {
  surveys: Survey[];
  onSurveySelect: (survey: Survey) => void;
  onSurveyDelete: (survey: Survey) => void;
  onSurveyDuplicate: (survey: Survey) => void;
  onSurveyCreate: () => void;
}

export const SurveyList: React.FC<SurveyListProps> = ({
  surveys,
  onSurveySelect,
  onSurveyDelete,
  onSurveyDuplicate,
  onSurveyCreate
}) => {
  const [searchTerm, setSearchTerm] = React.useState('');
  const [menuAnchorEl, setMenuAnchorEl] = React.useState<null | HTMLElement>(null);
  const [selectedSurvey, setSelectedSurvey] = React.useState<Survey | null>(null);
  const [deleteDialogOpen, setDeleteDialogOpen] = React.useState(false);

  const handleMenuOpen = (event: React.MouseEvent<HTMLElement>, survey: Survey) => {
    setMenuAnchorEl(event.currentTarget);
    setSelectedSurvey(survey);
  };

  const handleMenuClose = () => {
    setMenuAnchorEl(null);
    setSelectedSurvey(null);
  };

  const handleDeleteClick = () => {
    handleMenuClose();
    setDeleteDialogOpen(true);
  };

  const handleDeleteConfirm = () => {
    if (selectedSurvey) {
      onSurveyDelete(selectedSurvey);
    }
    setDeleteDialogOpen(false);
    setSelectedSurvey(null);
  };

  const filteredSurveys = surveys.filter(survey =>
    survey.name.toLowerCase().includes(searchTerm.toLowerCase())
  );

  return (
    <Box sx={{ width: '100%', maxWidth: 800, mx: 'auto', p: 3 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', mb: 3 }}>
        <Typography variant="h5" component="h1" sx={{ flexGrow: 1 }}>
          השאלונים שלי
        </Typography>
        <Button
          variant="contained"
          startIcon={<Add />}
          onClick={onSurveyCreate}
        >
          שאלון חדש
        </Button>
      </Box>

      <TextField
        fullWidth
        placeholder="חיפוש שאלונים..."
        value={searchTerm}
        onChange={(e) => setSearchTerm(e.target.value)}
        InputProps={{
          startAdornment: (
            <InputAdornment position="start">
              <Search />
            </InputAdornment>
          ),
        }}
        sx={{ mb: 3 }}
      />

      <Paper elevation={2}>
        <List>
          {filteredSurveys.map((survey) => (
            <ListItem
              key={survey.name}
              button
              onClick={() => onSurveySelect(survey)}
            >
              <ListItemText
                primary={survey.name}
                secondary={
                  <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.5, mt: 0.5 }}>
                    {survey.trigger_phrases.map((phrase) => (
                      <Chip
                        key={phrase}
                        label={phrase}
                        size="small"
                        sx={{ maxWidth: 150 }}
                      />
                    ))}
                  </Box>
                }
              />
              <ListItemSecondaryAction>
                <IconButton
                  edge="end"
                  onClick={(e) => handleMenuOpen(e, survey)}
                >
                  <MoreVert />
                </IconButton>
              </ListItemSecondaryAction>
            </ListItem>
          ))}
        </List>
      </Paper>

      <Menu
        anchorEl={menuAnchorEl}
        open={Boolean(menuAnchorEl)}
        onClose={handleMenuClose}
      >
        <MenuItem onClick={() => {
          handleMenuClose();
          if (selectedSurvey) onSurveySelect(selectedSurvey);
        }}>
          <Edit sx={{ mr: 1 }} /> ערוך
        </MenuItem>
        <MenuItem onClick={() => {
          handleMenuClose();
          if (selectedSurvey) onSurveyDuplicate(selectedSurvey);
        }}>
          <ContentCopy sx={{ mr: 1 }} /> שכפל
        </MenuItem>
        <MenuItem onClick={handleDeleteClick}>
          <Delete sx={{ mr: 1 }} color="error" /> מחק
        </MenuItem>
        <MenuItem onClick={handleMenuClose}>
          <Download sx={{ mr: 1 }} /> ייצא
        </MenuItem>
        <MenuItem onClick={handleMenuClose}>
          <Upload sx={{ mr: 1 }} /> ייבא
        </MenuItem>
      </Menu>

      <Dialog
        open={deleteDialogOpen}
        onClose={() => setDeleteDialogOpen(false)}
      >
        <DialogTitle>מחיקת שאלון</DialogTitle>
        <DialogContent>
          <DialogContentText>
            האם אתה בטוח שברצונך למחוק את השאלון "{selectedSurvey?.name}"?
            פעולה זו אינה הפיכה.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setDeleteDialogOpen(false)}>ביטול</Button>
          <Button onClick={handleDeleteConfirm} color="error" variant="contained">
            מחק
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}; 