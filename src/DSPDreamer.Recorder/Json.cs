using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text;

namespace DSPDreamer.Recorder
{
    internal static class Json
    {
        internal static Dictionary<string, object> Fields(params object[] pairs)
        {
            var result = new Dictionary<string, object>();
            for (int i = 0; i < pairs.Length; i += 2) result.Add((string)pairs[i], pairs[i + 1]);
            return result;
        }

        internal static string Encode(object value)
        {
            if (value == null) return "null";
            if (value is string text)
            {
                var result = new StringBuilder("\"");
                foreach (char c in text)
                {
                    if (c == '"' || c == '\\') result.Append('\\').Append(c);
                    else if (c < 32) result.Append("\\u").Append(((int)c).ToString("x4"));
                    else result.Append(c);
                }
                return result.Append('"').ToString();
            }
            if (value is bool flag) return flag ? "true" : "false";
            if (value is IDictionary<string, object> map)
                return "{" + string.Join(",", map.OrderBy(p => p.Key, StringComparer.Ordinal).Select(p => Encode(p.Key) + ":" + Encode(p.Value))) + "}";
            if (value is IEnumerable items) return "[" + string.Join(",", items.Cast<object>().Select(Encode)) + "]";
            string number = Convert.ToString(value, CultureInfo.InvariantCulture);
            if (number == "NaN" || number.Contains("Infinity")) throw new ArgumentException("Nonfinite JSON number");
            return number;
        }
    }
}
