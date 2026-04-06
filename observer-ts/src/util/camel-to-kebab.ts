/** Convert "UserService" to "user-service". */
export function camelToKebab(s: string): string {
  let result = "";
  for (let i = 0; i < s.length; i++) {
    const ch = s[i]!;
    if (ch >= "A" && ch <= "Z") {
      if (i > 0) result += "-";
      result += ch.toLowerCase();
    } else {
      result += ch;
    }
  }
  return result;
}
