pub fn answer() -> u8 { 42 }

#[cfg(test)]
mod tests { #[test] fn smoke() { assert_eq!(super::answer(), 42); } }
