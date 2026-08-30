/**
 * Transport mock: phát lại kịch bản 8 bước ngay trong trình duyệt.
 *
 * Phát ra ĐÚNG loại `ServerEvent` mà backend thật sẽ gửi. Khi backend xong,
 * đổi `VITE_TRANSPORT=live` là chuyển sang WebSocket, không sửa store.
 */
import type { ClientCommand, ServerEvent } from '../../types/transport'
import type { InspectedElementContext } from '../../types/inspect'
import { buildInspectedElementChunk } from '../inspect/chunk'
import {
  SCENARIO_STEPS,
  SCENARIO_TOTAL,
  REQ_FETCH_EXFIL,
  REQ_WRITE_AUTH,
  eventsForFetchDecision,
  eventsForWriteAuthDecision,
} from '../mock/scenario'
import type { PermissionButtonId } from '../permissions'
import { BaseTransport } from './types'

/** Chỉ số bước S3 (thẻ chuyển chế độ) và S4 (đã chuyển) trong SCENARIO_STEPS. */
const STEP_MODE_SWITCH_CARD = 2
const STEP_MODE_SWITCHED = 3

const DECISION_LABEL: Record<PermissionButtonId, string> = {
  cho_phep_mot_lan: 'Cho phép một lần',
  chuan_thuan_artifact: 'Tôi đã đọc và chấp nhận nguồn này',
  cap_giay_phep: 'Cấp giấy phép cho phạm vi này',
  tu_choi: 'Từ chối',
}

export class MockTransport extends BaseTransport {
  readonly kind = 'mock' as const

  private index = 0
  private rejectBundle = false

  async connect(_sessionId: string): Promise<void> {
    void _sessionId
    this.setStatus('connecting')
    this.setStatus('connected')
  }

  disconnect(): void {
    this.setStatus('disconnected')
  }

  send(command: ClientCommand): void {
    switch (command.type) {
      case 'scenario_step':
        this.playNext()
        break

      case 'scenario_reset':
        this.index = 0
        this.emit({ type: 'task_finished', reason: 'reset' })
        this.emit({ type: 'scenario_progress', index: 0, total: SCENARIO_TOTAL })
        this.playStep(0)
        break

      case 'scenario_set_reject_bundle':
        this.rejectBundle = command.value
        break

      case 'user_message':
        this.emit({
          type: 'user_message_echo',
          message_id: `m-user-${Date.now()}`,
          text: command.text,
        })
        // Nạp mọi phần tử đã đính kèm (chip khung ④) vào ngữ cảnh TRƯỚC khi
        // báo hệ thống, đúng như box thật sẽ làm cho `elements` — để bản mock
        // tự giải thích tính năng mà không cần backend (F7, §8-F7).
        for (const element of command.elements ?? []) {
          this.emit({ type: 'label_added', chunk: buildInspectedElementChunk(element) })
        }
        this.emit({
          type: 'system_note',
          message_id: `m-mock-${Date.now()}`,
          text: this.userMessageNote(command.elements),
        })
        break

      case 'mode_switch_request':
        // Công tắc Plan/Act KHÔNG tự đổi chế độ — nó chỉ yêu cầu backend dựng
        // thẻ chuyển chế độ để người dùng đọc kế hoạch rồi tự quyết định.
        if (this.index <= STEP_MODE_SWITCH_CARD) {
          this.playStep(STEP_MODE_SWITCH_CARD)
          this.index = STEP_MODE_SWITCH_CARD + 1
          this.emitProgress()
        }
        break

      case 'mode_switch_confirm':
        if (command.accepted) {
          this.playStep(STEP_MODE_SWITCHED)
          this.index = Math.max(this.index, STEP_MODE_SWITCHED + 1)
          this.emitProgress()
        } else {
          this.emit({
            type: 'system_note',
            message_id: `m-plan-edit-${Date.now()}`,
            text: 'You chose to edit the plan. Session remains in PLAN mode, no execution lease granted.',
          })
        }
        break

      case 'permission_response':
        this.resolvePermission(command.request_id, command.button)
        break

      case 'revoke_lease':
        this.emit({
          type: 'lease_invalidated',
          lease_id: command.lease_id,
          status: 'bi_thu_hoi',
          reason: 'User manually revoked lease in Labels & Leases panel.',
        })
        break

      case 'interrupt':
        this.emit({
          type: 'system_note',
          message_id: `m-int-${Date.now()}`,
          text: `Received interrupt command (level "${command.level}").`,
        })
        break

      case 'screen_offer':
      case 'screen_answer':
      case 'screen_ice':
        // Bản mock không có WebRTC — bỏ qua signaling.
        break
    }
  }

  /**
   * Nội dung `system_note` sau `user_message`. Khi có `elements` đính kèm,
   * nói rõ số lượng, nhãn KHÔNG TIN ĐƯỢC, và `integrity_floor` của phiên vừa
   * sụt — nếu không nói thì bản mock âm thầm đổi hành vi mà không giải thích.
   */
  private userMessageNote(elements: InspectedElementContext[] | undefined): string {
    if (!elements || elements.length === 0) {
      return (
        'Đang chạy bản MOCK, chưa nối backend nên agent không trả lời câu tự do. ' +
        'Dùng nút "Bước tiếp" ở bộ điều khiển demo để chạy kịch bản.'
      )
    }
    return (
      `Đã nạp ${elements.length} phần tử từ khung ④ vào ngữ cảnh, nhãn KHÔNG TIN ĐƯỢC ` +
      '(khong_tin_duoc) — integrity_floor của phiên vừa sụt theo. Đang chạy bản MOCK, ' +
      'chưa nối backend nên agent không trả lời câu tự do.'
    )
  }

  private resolvePermission(requestId: string, button: PermissionButtonId): void {
    const allowed = button !== 'tu_choi'
    this.emit({
      type: 'permission_resolved',
      request_id: requestId,
      decision: button,
      status: 'da_quyet_dinh',
    })
    if (requestId === REQ_WRITE_AUTH) {
      this.emitAll(eventsForWriteAuthDecision(allowed, DECISION_LABEL[button]))
    } else if (requestId === REQ_FETCH_EXFIL) {
      this.emitAll(eventsForFetchDecision(allowed))
    }
  }

  private playNext(): void {
    if (this.index >= SCENARIO_TOTAL) return
    this.playStep(this.index)
    this.index += 1
    this.emitProgress()
  }

  private playStep(stepIndex: number): void {
    const step: ServerEvent[] = SCENARIO_STEPS[stepIndex].events({ rejectBundle: this.rejectBundle })
    this.emitAll(step)
    if (stepIndex === 0) {
      this.index = 1
      this.emitProgress()
    }
  }

  private emitProgress(): void {
    this.emit({ type: 'scenario_progress', index: this.index, total: SCENARIO_TOTAL })
  }
}
