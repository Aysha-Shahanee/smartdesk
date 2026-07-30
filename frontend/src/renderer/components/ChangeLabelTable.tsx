import React, { useEffect, useState } from 'react';
import { getAllSegments, recordCorrection } from '../services/api';
import { useDateContext } from '../contexts/DateContext';
import { formatSegmentTime } from '../utils/time';
import '../pages/Timeline.css'; // Reuse Timeline styles for the table

const availableLabels = ['Work', 'Learn', 'Communication', 'Entertainment', 'Social Media', 'System', 'Meetings', 'Idle', 'Other'];

export const ChangeLabelTable: React.FC = () => {
  const { selectedDate } = useDateContext();
  const [segments, setSegments] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [tempLabel, setTempLabel] = useState<string>('');
  const [saving, setSaving] = useState(false);
  const [visibleRows, setVisibleRows] = useState(5);

  useEffect(() => {
    const fetchSegments = async () => {
      setLoading(true);
      try {
        setSegments(await getAllSegments(selectedDate));
      } catch (err) {
        console.error('Failed to load segments for change label UI', err);
      } finally {
        setLoading(false);
      }
    };
    fetchSegments();
  }, [selectedDate]);

  const handleEdit = (segment: any) => {
    setEditingId(segment.id);
    setTempLabel(segment.correction_label || segment.predicted_category || '');
  };

  const handleSave = async (id: string) => {
    if (!tempLabel) return;
    setSaving(true);
    try {
      const formattedLabel = tempLabel.toLowerCase().replace(/ /g, '_');
      await recordCorrection(id, formattedLabel);
      // Optimistic update
      setSegments(prev => prev.map(s => s.id === id ? { ...s, correction_label: formattedLabel } : s));
      setEditingId(null);
    } catch (err) {
      console.error('Failed to save correction', err);
      alert('Failed to save correction.');
    } finally {
      setSaving(false);
    }
  };

  const handleCancel = () => {
    setEditingId(null);
    setTempLabel('');
  };

  if (loading) {
    return <div className="sd-loader">Loading segments for {selectedDate}...</div>;
  }

  if (segments.length === 0) {
    return <p className="sd-text-muted">No segments found for this date.</p>;
  }

  return (
    <div className="change-label-section sd-card">
      <div className="card-header">
        <h3>Change Label for {selectedDate}</h3>
        <span className="label-count">{segments.length} segments</span>
      </div>
      <p className="label-description">Correct AI predictions to improve future accuracy. Changes save immediately.</p>
      
      <div className="label-table-wrapper">
        <table className="label-table">
          <thead>
            <tr>
              <th>Time</th>
              <th>Primary App</th>
              <th>Title / Context</th>
              <th>Predicted Label</th>
              <th>Confidence</th>
              <th>Correction</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {segments.slice(0, visibleRows).map((seg) => {
              // `start_time_utc` is misnamed: the builder derives `local_date`
              // from it with a bare `.date()`, so it already holds local wall
              // time. Appending 'Z' re-applied the UTC offset and shifted every
              // row here forward by the zone offset (+5:30), disagreeing with
              // the Timeline view of the very same segment.
              const startStr = formatSegmentTime(seg.start_time_utc);
              const endStr = formatSegmentTime(seg.end_time_utc);
              const isEditing = editingId === seg.id;
              
              const confScore = seg.predicted_confidence !== undefined ? seg.predicted_confidence : 0.85;
              const confClass = confScore >= 0.8 ? 'high' : confScore >= 0.6 ? 'medium' : 'low';

              return (
                <tr key={seg.id} className={seg.correction_label ? 'corrected-row' : ''}>
                  <td className="time-cell">{startStr} - {endStr}</td>
                  <td style={{ fontWeight: 500 }}>{seg.app_name || 'Unknown'}</td>
                  <td className="title-cell" title={seg.title}>{seg.title || '-'}</td>
                  <td>
                    <span className="category-badge" style={{ background: 'var(--color-bg)', border: '1px solid var(--color-border)' }}>
                      {seg.predicted_category}
                    </span>
                  </td>
                  <td className={`confidence ${confClass}`}>{Math.round(confScore * 100)}%</td>
                  <td>
                    {isEditing ? (
                      <select 
                        className="label-select" 
                        value={tempLabel} 
                        onChange={(e) => setTempLabel(e.target.value)}
                        autoFocus
                      >
                        <option value="">Select...</option>
                        {availableLabels.map(l => (
                          <option key={l} value={l}>{l}</option>
                        ))}
                      </select>
                    ) : (
                      seg.correction_label ? (
                        <span className="category-badge corrected">{seg.correction_label}</span>
                      ) : (
                        <span className="no-correction">-</span>
                      )
                    )}
                  </td>
                  <td>
                    {isEditing ? (
                      <div className="action-btns">
                        <button className="sd-btn sd-btn--primary save-btn" onClick={() => handleSave(seg.id)} disabled={saving}>
                          {saving ? '...' : 'Save'}
                        </button>
                        <button className="sd-btn cancel-btn" onClick={handleCancel} disabled={saving}>Cancel</button>
                      </div>
                    ) : (
                      <button className="edit-btn" onClick={() => handleEdit(seg)} title="Edit Label">
                        ✎
                      </button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {visibleRows < segments.length && (
        <div style={{ textAlign: 'center', marginTop: 'var(--space-md)' }}>
          <button 
            className="sd-btn sd-btn--secondary" 
            onClick={() => setVisibleRows(prev => prev + 10)}
          >
            See more...
          </button>
        </div>
      )}
    </div>
  );
};
