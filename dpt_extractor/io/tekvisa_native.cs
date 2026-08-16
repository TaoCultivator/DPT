using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

namespace Dpt.ScopeIo
{
    public sealed class TekVisaResourceManager : IDisposable
    {
        private const string TekVisaDll = @"C:\Program Files\IVI Foundation\VISA\Win64\TekVISA\Bin\tkVisa64.dll";
        private const int ViErrorResourceNotFound = unchecked((int)0xBFFF0011);
        private uint _session;

        public TekVisaResourceManager()
        {
            CheckStatus(Native.viOpenDefaultRM(out _session), 0, "viOpenDefaultRM");
        }

        public string[] Find(string expression)
        {
            ThrowIfDisposed();
            uint findList = 0;
            uint count = 0;
            var descriptor = new StringBuilder(256);
            int status = Native.viFindRsrc(
                _session,
                expression,
                out findList,
                out count,
                descriptor
            );
            if (status == ViErrorResourceNotFound)
            {
                return new string[0];
            }
            CheckStatus(status, _session, "viFindRsrc");

            int capacity = count > int.MaxValue ? int.MaxValue : (int)count;
            var resources = new List<string>(capacity);
            try
            {
                if (count > 0)
                {
                    resources.Add(descriptor.ToString());
                }
                for (uint index = 1; index < count; index++)
                {
                    descriptor.Clear();
                    CheckStatus(
                        Native.viFindNext(findList, descriptor),
                        _session,
                        "viFindNext"
                    );
                    resources.Add(descriptor.ToString());
                }
            }
            finally
            {
                if (findList != 0)
                {
                    Native.viClose(findList);
                }
            }
            return resources.ToArray();
        }

        public TekVisaMessageSession Open(string resourceName)
        {
            ThrowIfDisposed();
            uint session;
            CheckStatus(
                Native.viOpen(_session, resourceName, 0, 0, out session),
                _session,
                "viOpen"
            );
            return new TekVisaMessageSession(session);
        }

        public void Dispose()
        {
            if (_session != 0)
            {
                Native.viClose(_session);
                _session = 0;
            }
            GC.SuppressFinalize(this);
        }

        private void ThrowIfDisposed()
        {
            if (_session == 0)
            {
                throw new ObjectDisposedException("TekVisaResourceManager");
            }
        }

        internal static void CheckStatus(int status, uint session, string operation)
        {
            if (status >= 0)
            {
                return;
            }
            var description = new StringBuilder(512);
            string detail = string.Empty;
            if (session != 0 && Native.viStatusDesc(session, status, description) >= 0)
            {
                detail = description.ToString().Trim();
            }
            string suffix = string.IsNullOrWhiteSpace(detail) ? string.Empty : ": " + detail;
            throw new InvalidOperationException(
                string.Format(
                    "TekVISA {0} failed (0x{1:X8}){2}",
                    operation,
                    unchecked((uint)status),
                    suffix
                )
            );
        }

        internal static class Native
        {
            [DllImport(TekVisaDll, CallingConvention = CallingConvention.StdCall)]
            internal static extern int viOpenDefaultRM(out uint session);

            [DllImport(TekVisaDll, CallingConvention = CallingConvention.StdCall, CharSet = CharSet.Ansi)]
            internal static extern int viFindRsrc(
                uint session,
                string expression,
                out uint findList,
                out uint returnCount,
                StringBuilder descriptor
            );

            [DllImport(TekVisaDll, CallingConvention = CallingConvention.StdCall, CharSet = CharSet.Ansi)]
            internal static extern int viFindNext(uint findList, StringBuilder descriptor);

            [DllImport(TekVisaDll, CallingConvention = CallingConvention.StdCall, CharSet = CharSet.Ansi)]
            internal static extern int viOpen(
                uint resourceManager,
                string resourceName,
                uint accessMode,
                uint openTimeout,
                out uint session
            );

            [DllImport(TekVisaDll, CallingConvention = CallingConvention.StdCall)]
            internal static extern int viClose(uint sessionOrObject);

            [DllImport(TekVisaDll, CallingConvention = CallingConvention.StdCall)]
            internal static extern int viSetAttribute(uint session, uint attribute, ulong value);

            [DllImport(TekVisaDll, CallingConvention = CallingConvention.StdCall)]
            internal static extern int viRead(
                uint session,
                [Out] byte[] buffer,
                uint count,
                out uint returnCount
            );

            [DllImport(TekVisaDll, CallingConvention = CallingConvention.StdCall)]
            internal static extern int viWrite(
                uint session,
                byte[] buffer,
                uint count,
                out uint returnCount
            );

            [DllImport(TekVisaDll, CallingConvention = CallingConvention.StdCall)]
            internal static extern int viClear(uint session);

            [DllImport(TekVisaDll, CallingConvention = CallingConvention.StdCall)]
            internal static extern int viStatusDesc(
                uint session,
                int status,
                StringBuilder description
            );
        }
    }

    public sealed class TekVisaMessageSession : IDisposable
    {
        private const uint ViAttrTimeoutValue = 0x3FFF001A;
        private uint _session;
        private int _timeoutMilliseconds = 2000;
        private readonly TekVisaRawIo _rawIo;

        internal TekVisaMessageSession(uint session)
        {
            _session = session;
            _rawIo = new TekVisaRawIo(this);
            TimeoutMilliseconds = _timeoutMilliseconds;
        }

        public TekVisaRawIo RawIO
        {
            get { return _rawIo; }
        }

        public int TimeoutMilliseconds
        {
            get { return _timeoutMilliseconds; }
            set
            {
                ThrowIfDisposed();
                if (value < 0)
                {
                    throw new ArgumentOutOfRangeException("value");
                }
                TekVisaResourceManager.CheckStatus(
                    TekVisaResourceManager.Native.viSetAttribute(
                        _session,
                        ViAttrTimeoutValue,
                        unchecked((uint)value)
                    ),
                    _session,
                    "viSetAttribute(VI_ATTR_TMO_VALUE)"
                );
                _timeoutMilliseconds = value;
            }
        }

        public void Clear()
        {
            ThrowIfDisposed();
            TekVisaResourceManager.CheckStatus(
                TekVisaResourceManager.Native.viClear(_session),
                _session,
                "viClear"
            );
        }

        internal byte[] Read(long requestedCount)
        {
            ThrowIfDisposed();
            if (requestedCount <= 0 || requestedCount > int.MaxValue)
            {
                throw new ArgumentOutOfRangeException("requestedCount");
            }
            var buffer = new byte[(int)requestedCount];
            uint received;
            TekVisaResourceManager.CheckStatus(
                TekVisaResourceManager.Native.viRead(
                    _session,
                    buffer,
                    (uint)requestedCount,
                    out received
                ),
                _session,
                "viRead"
            );
            if (received == buffer.Length)
            {
                return buffer;
            }
            var result = new byte[received];
            Buffer.BlockCopy(buffer, 0, result, 0, (int)received);
            return result;
        }

        internal void Write(string value)
        {
            ThrowIfDisposed();
            byte[] bytes = Encoding.ASCII.GetBytes(value);
            uint written;
            TekVisaResourceManager.CheckStatus(
                TekVisaResourceManager.Native.viWrite(
                    _session,
                    bytes,
                    (uint)bytes.Length,
                    out written
                ),
                _session,
                "viWrite"
            );
            if (written != bytes.Length)
            {
                throw new InvalidOperationException(
                    string.Format(
                        "TekVISA viWrite was incomplete: expected {0} bytes, wrote {1}",
                        bytes.Length,
                        written
                    )
                );
            }
        }

        public void Dispose()
        {
            if (_session != 0)
            {
                TekVisaResourceManager.Native.viClose(_session);
                _session = 0;
            }
            GC.SuppressFinalize(this);
        }

        private void ThrowIfDisposed()
        {
            if (_session == 0)
            {
                throw new ObjectDisposedException("TekVisaMessageSession");
            }
        }
    }

    public sealed class TekVisaRawIo
    {
        private const int TextBufferSize = 1024 * 1024;
        private readonly TekVisaMessageSession _session;

        internal TekVisaRawIo(TekVisaMessageSession session)
        {
            _session = session;
        }

        public byte[] Read(long requestedCount)
        {
            return _session.Read(requestedCount);
        }

        public string ReadString()
        {
            return Encoding.ASCII.GetString(_session.Read(TextBufferSize));
        }

        public void Write(string value)
        {
            _session.Write(value);
        }
    }
}
