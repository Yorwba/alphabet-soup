package com.yorwba.kuromoji;

import com.atilika.kuromoji.unidic.kanaaccent.Token;
import com.atilika.kuromoji.unidic.kanaaccent.Tokenizer;
import java.util.HashMap;
import java.util.List;
import java.util.Set;
import java.util.regex.Pattern;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.io.IOException;

public class KuromojiTokenize {
    private static final Pattern furiganaPattern = Pattern.compile("\\[([^|]+)\\|([^\\]]+)\\]");

    private static final Tokenizer tokenizer = new Tokenizer();

    private static HashMap<String, List<Token>> multiNBest(String text, int n) {
        HashMap<String, List<Token>> multiTokens = new HashMap<String, List<Token>>();
        for(List<?> tokenBases : tokenizer.multiTokenizeNBest(text, 100)) {
            List<Token> tokens = (List<Token>) tokenBases;
            String pronunciation = "";
            for(Token token : tokens) {
                pronunciation += token.getPronunciation();
            }
            if(multiTokens.get(pronunciation) == null) {
                // this tokenization is best for the pronunciation
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
        HashMap<String, List<Token>> kanjiNBest = multiNBest(kanji, 100);

        HashMap<String, List<Token>> furiganaNBest = multiNBest(furigana, 100);
        Set<String> commonPronunciations = kanjiNBest.keySet();
        commonPronunciations.retainAll(furiganaNBest.keySet());
        for(String pronunciation : commonPronunciations) {
            return kanjiNBest.get(pronunciation);
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
