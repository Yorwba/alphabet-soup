/**
 *  Alphabet Soup gives language learners easily digestible chunks for practice.
 *  Copyright 2019-2020 Yorwba
 *
 *  Alphabet Soup is free software: you can redistribute it and/or
 *  modify it under the terms of the GNU Affero General Public License
 *  as published by the Free Software Foundation, either version 3 of
 *  the License, or (at your option) any later version.
 *
 *  Alphabet Soup is distributed in the hope that it will be useful,
 *  but WITHOUT ANY WARRANTY; without even the implied warranty of
 *  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 *  GNU Affero General Public License for more details.
 *
 *  You should have received a copy of the GNU Affero General Public License
 *  along with Alphabet Soup.  If not, see <https://www.gnu.org/licenses/>.
 */

package com.yorwba.kuromoji;

import com.atilika.kuromoji.unidic.kanaaccent.Token;
import com.atilika.kuromoji.unidic.kanaaccent.Tokenizer;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.IOException;

public class KuromojiTokenize {
    private static final Pattern furiganaPattern = Pattern.compile("\\[([^|]+)\\|([^\\]]+)\\]");

    private static final Tokenizer tokenizer = new Tokenizer();

    private static LinkedHashMap<String, List<Token>> multiNBest(String text, int n) {
        LinkedHashMap<String, List<Token>> multiTokens = new LinkedHashMap<String, List<Token>>();
        for(List<?> tokenBases : tokenizer.multiTokenizeNBest(text, 100)) {
            List<Token> tokens = (List<Token>) tokenBases;
            String pronunciation = "";
            for(Token token : tokens) {
                pronunciation += token.getPronunciation();
            }
            if(multiTokens.get(pronunciation) == null) {
                // this tokenization is the first and best for the pronunciation
                multiTokens.put(pronunciation, tokens);
            }
        }
        return multiTokens;
    }

    private static List<Token> tokenizeWithFurigana(String text) {
        String kanji = furiganaPattern.matcher(text).replaceAll("$1");
        String furigana = furiganaPattern.matcher(text).replaceAll("$2");
        if(kanji.equals(furigana)) {
            return tokenizer.tokenize(kanji);
        }
        LinkedHashMap<String, List<Token>> kanjiNBest = multiNBest(kanji, 100);

        LinkedHashMap<String, List<Token>> furiganaNBest = multiNBest(furigana, 100);
        for(Map.Entry<String, List<Token>> e : kanjiNBest.entrySet()) {
            if(furiganaNBest.containsKey(e.getKey())) { // pronunciation matches furigana
                return e.getValue();
            }
        }

        // No common pronunciation.
        return tokenizer.tokenize(kanji);
    }

    public static void main(String[] args) {
        BufferedReader reader = new BufferedReader(new InputStreamReader(System.in));
        String line;
        try {
            while(null != (line = reader.readLine())) {
                for (Token token : tokenizeWithFurigana(line)) {
                    System.out.println(
                            token.getSurface() + "\t"
                            + token.getPartOfSpeechLevel1() + ","
                            + token.getPartOfSpeechLevel2() + ","
                            + token.getPartOfSpeechLevel3() + ","
                            + token.getPartOfSpeechLevel4() + ","
                            + token.getConjugationType() + ","
                            + token.getConjugationForm() + ","
                            + token.getLemma() + ","
                            + getAccentedPronunciation(token)
                    );
                }
                System.out.println("EOS");
            }
        } catch(IOException e) { }
    }

    private static String getAccentedPronunciation(Token token) {
        String accentType = token.getAccentType();
        String unaccented = token.getPronunciation();
        if(accentType.equals("*")) {
            return unaccented;
        }
        int comma = accentType.indexOf(",");
        if(comma != -1) {
            accentType = accentType.substring(0, comma);
        }
        int accentedMora = Integer.parseInt(accentType);
        if(accentedMora == 0) {
            return unaccented;
        }
        int accent, morae;
        for(accent = 0, morae = 0; morae <= accentedMora && accent < unaccented.length(); accent++) {
            switch(unaccented.charAt(accent)) {
                case 'ァ': case 'ィ': case 'ゥ': case 'ェ':
                case 'ォ': case 'ャ': case 'ュ': case 'ョ': continue;
                default: morae++;
            }
        }
        if(morae > accentedMora) { // overshot
            accent--;
        }
        return unaccented.substring(0, accent)
            + "↘" + unaccented.substring(accent, unaccented.length());
    }
}
