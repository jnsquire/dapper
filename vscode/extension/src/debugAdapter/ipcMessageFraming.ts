export const IPC_MESSAGE_KIND_EVENT = 1;
export const IPC_MESSAGE_KIND_COMMAND = 2;

export type IpcMessageKind = typeof IPC_MESSAGE_KIND_EVENT | typeof IPC_MESSAGE_KIND_COMMAND;

interface IpcWritable {
  write(data: Uint8Array | string): unknown;
}

export function createIpcMessageFrame(payload: unknown, kind: IpcMessageKind = IPC_MESSAGE_KIND_EVENT): Buffer {
  const payloadBuffer = Buffer.from(JSON.stringify(payload), 'utf8');
  const header = Buffer.alloc(8);
  header.write('DP', 0);
  header.writeUInt8(1, 2);
  header.writeUInt8(kind, 3);
  header.writeUInt32BE(payloadBuffer.length, 4);
  return Buffer.concat([header, payloadBuffer]);
}

export function writeIpcMessage(
  socket: IpcWritable,
  payload: unknown,
  kind: IpcMessageKind = IPC_MESSAGE_KIND_EVENT,
): void {
  socket.write(createIpcMessageFrame(payload, kind));
}